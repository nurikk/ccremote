"""Message relay — single session, DM, sendMessageDraft streaming."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Bot, Dispatcher
    from aiogram.types import Message

    from ccremote.config import Configuration
    from ccremote.models import Session

logger = logging.getLogger(__name__)


# ── Event parsing ──────────────────────────────────────────────────


def parse_claude_event(event: dict) -> dict:
    match event:
        case {"type": "system", "subtype": "init"}:
            return {
                "type": "init",
                "session_id": event.get("session_id", ""),
                "slash_commands": event.get("slash_commands", []),
            }
        case {"type": "system", "subtype": "api_retry"}:
            return {
                "type": "api_retry",
                "attempt": event.get("attempt", 0),
                "error": event.get("error", ""),
            }
        case {"type": "assistant", "message": {"content": list(content)}}:
            text_parts = []
            tool_uses = []
            for block in content:
                match block:
                    case {"type": "text", "text": str(t)}:
                        text_parts.append(t)
                    case {"type": "tool_use", "name": str(name)}:
                        tool_uses.append({
                            "name": name,
                            "id": block.get("id", ""),
                            "input": block.get("input", {}),
                        })
            return {"type": "assistant", "text": "\n".join(text_parts), "tool_uses": tool_uses}
        case {"type": "user", "message": {"content": list(content)}}:
            results = []
            for block in content:
                match block:
                    case {"type": "tool_result", "tool_use_id": str(tid)}:
                        results.append({
                            "tool_use_id": tid,
                            "content": str(block.get("content", ""))[:200],
                        })
            tool_info = event.get("tool_use_result", {})
            if not isinstance(tool_info, dict):
                tool_info = {}
            return {
                "type": "tool_result",
                "results": results,
                "duration_ms": tool_info.get("durationMs"),
                "filenames": tool_info.get("filenames", []),
            }
        case {"type": "stream_event", "event": dict(inner)}:
            return _parse_stream_event(inner)
        case {"type": "result"}:
            return {
                "type": "result",
                "text": event.get("result", ""),
                "is_error": event.get("is_error", False),
                "cost_usd": event.get("total_cost_usd"),
                "num_turns": event.get("num_turns"),
                "permission_denials": event.get("permission_denials", []),
            }
        case _:
            return {"type": "unknown"}


def _parse_stream_event(inner: dict) -> dict:
    match inner:
        case {"type": "content_block_start", "content_block": {"type": "tool_use", "name": str(name)}}:
            return {"type": "tool_start", "name": name, "id": inner["content_block"].get("id", "")}
        case {"type": "content_block_start", "content_block": {"type": "thinking"}}:
            return {"type": "thinking_start"}
        case {"type": "content_block_start", "content_block": dict(block)}:
            return {"type": "block_start", "block_type": block.get("type", "")}
        case {"type": "content_block_delta", "delta": {"type": "text_delta", "text": str(t)}}:
            return {"type": "text_delta", "text": t}
        case {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": str(j)}}:
            return {"type": "input_delta", "json": j}
        case {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": str(t)}}:
            return {"type": "thinking_delta", "text": t}
        case {"type": "content_block_delta"}:
            return {"type": "delta_other"}
        case {"type": "content_block_stop"}:
            return {"type": "block_stop"}
        case {"type": str(t)} if t in ("message_start", "message_delta", "message_stop"):
            return {"type": t}
        case _:
            return {"type": "stream_other"}


def normalize_slash_commands(raw_commands: list[dict]) -> list[tuple[str, str]]:
    result = []
    for cmd in raw_commands:
        raw_name = cmd.get("name", "") if isinstance(cmd, dict) else str(cmd)
        desc = cmd.get("description", "") if isinstance(cmd, dict) else ""
        raw_name = raw_name.lstrip("/")
        if ":" in raw_name:
            continue
        name = re.sub(r"[^a-z0-9_]", "_", raw_name.lower())[:32]
        if name:
            result.append((name, desc[:256]))
    return result


# ── Draft builder ──────────────────────────────────────────────────


class DraftBuilder:
    """Builds streaming draft text from Claude events."""

    def __init__(self, max_length: int = 4000) -> None:
        self.max_length = max_length
        self.response_text = ""
        self.thinking_text = ""
        self.active_tool: str | None = None
        self.tool_input_json = ""
        self.tool_log: list[str] = []
        self.is_thinking = False
        self.cost_usd: float | None = None
        self.num_turns: int | None = None
        self.permission_denials: list[dict] = []

    def process(self, parsed: dict) -> None:
        ptype = parsed.get("type")

        if ptype == "text_delta":
            self.response_text += parsed.get("text", "")
        elif ptype == "thinking_start":
            self.is_thinking = True
            self.thinking_text = ""
        elif ptype == "thinking_delta":
            self.thinking_text += parsed.get("text", "")
        elif ptype == "tool_start":
            self.active_tool = parsed.get("name", "")
            self.tool_input_json = ""
        elif ptype == "input_delta":
            self.tool_input_json += parsed.get("json", "")
        elif ptype == "block_stop":
            if self.active_tool:
                self.tool_log.append(self._format_tool_summary())
                self.active_tool = None
                self.tool_input_json = ""
            if self.is_thinking:
                self.is_thinking = False
        elif ptype == "tool_result":
            for r in parsed.get("results", []):
                line = f"  ↳ {r.get('content', '')[:100]}"
                duration = parsed.get("duration_ms")
                if duration:
                    line += f" ({duration}ms)"
                self.tool_log.append(line)
            for f in parsed.get("filenames", [])[:3]:
                self.tool_log.append(f"  📄 {f}")
        elif ptype == "assistant":
            text = parsed.get("text", "")
            if text:
                self.response_text = text
            for tool in parsed.get("tool_uses", []):
                self.tool_log.append(f"🔧 {tool['name']}")
        elif ptype == "api_retry":
            self.tool_log.append(f"⚠️ Retry #{parsed.get('attempt', 0)}: {parsed.get('error', '')}")
        elif ptype == "result":
            text = parsed.get("text", "")
            if text:
                self.response_text = text
            self.cost_usd = parsed.get("cost_usd")
            self.num_turns = parsed.get("num_turns")
            self.permission_denials = parsed.get("permission_denials", [])

    def _format_tool_summary(self) -> str:
        name = self.active_tool or "unknown"
        try:
            inp = json.loads(self.tool_input_json) if self.tool_input_json else {}
        except json.JSONDecodeError:
            inp = {}
        if name in ("Read", "Glob", "Grep"):
            target = inp.get("file_path") or inp.get("pattern") or inp.get("path", "")
            return f"🔍 {name}: {target}"
        elif name in ("Write", "Edit"):
            return f"✏️ {name}: {inp.get('file_path', '')}"
        elif name == "Bash":
            return f"💻 Bash: {inp.get('command', '')[:60]}"
        return f"🔧 {name}"

    def build_draft(self) -> str:
        parts = []
        if self.tool_log:
            parts.append("\n".join(self.tool_log[-10:]))
        if self.active_tool:
            parts.append(f"⏳ {self.active_tool}...")
        if self.is_thinking and self.thinking_text:
            parts.append(f"💭 {self.thinking_text[-200:]}")
        elif self.is_thinking:
            parts.append("💭 Thinking...")
        if self.response_text:
            parts.append("───")
            parts.append(self.response_text)
        text = "\n".join(parts) if parts else "..."
        return text[: self.max_length]

    def build_final(self) -> str:
        text = self.response_text or "(no response)"
        if self.cost_usd is not None:
            text += f"\n\n`${self.cost_usd}`"
        return text[: self.max_length]


# ── Handlers ───────────────────────────────────────────────────────


async def download_attachment(bot: Bot, message: Message, work_dir: str) -> Path | None:
    """Download a photo or document from the message to the working directory."""
    attachments_dir = Path(work_dir) / ".ccremote-attachments"
    attachments_dir.mkdir(exist_ok=True)

    try:
        if message.photo:
            photo = message.photo[-1]  # largest size
            file = await bot.get_file(photo.file_id)
            ext = Path(file.file_path).suffix or ".jpg"
            dest = attachments_dir / f"{photo.file_unique_id}{ext}"
            await bot.download_file(file.file_path, dest)
            return dest

        if message.document:
            file = await bot.get_file(message.document.file_id)
            name = message.document.file_name or message.document.file_unique_id
            dest = attachments_dir / name
            await bot.download_file(file.file_path, dest)
            return dest
    except Exception:
        logger.exception("Failed to download attachment")

    return None


async def transcribe_voice(bot: Bot, message: Message, config: Configuration) -> str | None:
    """Download a voice message and transcribe it with OpenAI Whisper."""
    if not config.openai_api_key:
        logger.warning("Voice message received but CCREMOTE_OPENAI_API_KEY not set")
        return None

    try:
        import aiohttp

        file = await bot.get_file(message.voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            await bot.download_file(file.file_path, tmp)

        form = aiohttp.FormData()
        form.add_field("model", "whisper-1")
        with open(tmp_path, "rb") as audio_file:
            form.add_field(
                "file", audio_file, filename="voice.ogg", content_type="audio/ogg",
            )
            async with (
                aiohttp.ClientSession() as http,
                http.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {config.openai_api_key}"},
                    data=form,
                ) as resp,
            ):
                resp.raise_for_status()
                result = await resp.json()

        tmp_path.unlink(missing_ok=True)
        text = result.get("text", "")
        logger.info("Transcribed voice (%ds): %s", message.voice.duration, text[:80])
        return text
    except Exception:
        logger.exception("Voice transcription failed")
        return None


def setup_relay_handlers(
    dp: Dispatcher,
    bot: Bot,
    session: Session,
    config: Configuration,
) -> None:
    """Register DM message handler — routes all messages to the active session."""
    from aiogram.types import CallbackQuery, Message
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    # Store pending retries: callback_id -> (prompt, denied_tools)
    pending_retries: dict[str, tuple[str, list[str]]] = {}

    @dp.message()
    async def handle_dm(message: Message) -> None:
        text = message.text or message.caption or ""

        if message.voice:
            transcription = await transcribe_voice(bot, message, config)
            if transcription:
                text = transcription

        if message.photo or message.document:
            path = await download_attachment(bot, message, session.working_directory)
            if path:
                text = f"{text}\n\n[User sent you a file: {path}]".strip() if text else f"User sent you a file: {path}"

        if not text:
            return

        if text.strip().lower() == "/clear":
            session.claude_session_id = ""
            logger.info("Session cleared by user %s", message.from_user.id)
            await bot.send_message(chat_id=message.chat.id, text="Session cleared.")
            return

        logger.info("DM from %s → session %s", message.from_user.id, session.session_id[:8])

        session.last_message_at = datetime.now(UTC)

        task = asyncio.create_task(
            _run_relay(text, message.chat.id)
        )
        task.add_done_callback(lambda t: t.result() if not t.cancelled() else None)

    async def _run_relay(
        prompt: str, chat_id: int, allowed_tools: list[str] | None = None,
    ) -> None:
        from ccremote.bot import send_message

        denials = await relay_prompt_to_claude(
            prompt, session, chat_id, bot, config,
            allowed_tools=allowed_tools,
        )
        if not denials:
            return

        denied_tools = list({d.get("tool_name", "") for d in denials if d.get("tool_name")})
        denied_details = []
        for d in denials:
            tool = d.get("tool_name", "")
            inp = d.get("tool_input", {})
            if isinstance(inp, dict):
                detail = inp.get("command") or inp.get("file_path") or ""
            else:
                detail = str(inp)[:80]
            denied_details.append(f"{tool}: {detail}" if detail else tool)
        callback_id = f"perm_{hash(prompt + str(time.monotonic())) & 0xFFFFFF:06x}"
        pending_retries[callback_id] = (prompt, denied_tools)

        tools_desc = "\n".join(f"  • {d}" for d in denied_details)
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Allow & Retry", callback_data=f"{callback_id}:allow")
        kb.button(text="❌ Skip", callback_data=f"{callback_id}:skip")
        kb.adjust(2)

        await bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ Permission denied:\n{tools_desc}\n\nAllow and retry?",
            reply_markup=kb.as_markup(),
        )

    @dp.callback_query(lambda c: c.data and c.data.startswith("perm_"))
    async def handle_permission_callback(callback: CallbackQuery) -> None:
        callback_id, action = callback.data.rsplit(":", 1)

        if callback_id not in pending_retries:
            await callback.answer("Expired")
            return

        prompt, denied_tools = pending_retries.pop(callback_id)

        if action == "allow":
            await callback.answer("Retrying with permissions...")
            await callback.message.edit_text(
                f"✅ Allowed: {', '.join(denied_tools)} — retrying..."
            )
            task = asyncio.create_task(
                _run_relay(prompt, callback.message.chat.id, allowed_tools=denied_tools)
            )
            task.add_done_callback(lambda t: t.result() if not t.cancelled() else None)
        else:
            await callback.answer("Skipped")
            await callback.message.edit_text("⏭ Skipped permission request.")


async def relay_prompt_to_claude(
    prompt: str,
    session: Session,
    chat_id: int,
    bot: Bot,
    config: Configuration,
    allowed_tools: list[str] | None = None,
) -> list[dict]:
    """Spawn claude -p and stream output via sendMessageDraft.

    Returns list of permission denials (empty if none).
    """
    from ccremote.bot import register_commands, send_draft, send_message

    logger.info("Relaying to claude session %s: %s", session.session_id[:8], prompt[:80])

    args = [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    if session.claude_session_id:
        args.extend(["--resume", session.claude_session_id])

    if allowed_tools:
        args.extend(["--allowedTools", ",".join(allowed_tools)])

    if config.include_partial_messages:
        args.append("--include-partial-messages")

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=10 * 1024 * 1024,  # 10MB line buffer
            cwd=session.working_directory,
        )
    except FileNotFoundError:
        await send_message(bot, chat_id, "Error: claude CLI not found.")
        return []

    session.process_pid = proc.pid
    draft = DraftBuilder(config.max_message_length)
    draft_id = hash(session.session_id + str(time.monotonic())) & 0x7FFFFFFF
    last_draft_time = 0.0
    throttle_s = config.draft_throttle_ms / 1000.0

    try:
        while True:
            line = await proc.stdout.readline()  # type: ignore[union-attr]
            if not line:
                break
            try:
                event = json.loads(line.decode())
            except json.JSONDecodeError:
                continue

            parsed = parse_claude_event(event)

            if parsed["type"] == "init":
                new_sid = parsed.get("session_id", "")
                if new_sid and not session.claude_session_id:
                    session.claude_session_id = new_sid
                slash_cmds = parsed.get("slash_commands", [])
                logger.info("Raw slash_commands from init: %s", slash_cmds[:3])
                if slash_cmds:
                    session.slash_commands = normalize_slash_commands(slash_cmds)
                    session.slash_commands.append(("clear", "Start a new session"))
                    logger.info("Normalized %d slash commands: %s", len(session.slash_commands), session.slash_commands)
                    await register_commands(bot, chat_id, session.slash_commands)
                continue

            draft.process(parsed)

            now = time.monotonic()
            if now - last_draft_time >= throttle_s:
                draft_text = draft.build_draft()
                if draft_text:
                    await send_draft(bot, chat_id, draft_text, draft_id)
                    last_draft_time = now

        final_text = draft.build_final()
        await send_message(bot, chat_id, final_text)
        return draft.permission_denials

    except Exception:
        logger.exception("Error during relay for session %s", session.session_id)
        await send_message(bot, chat_id, "Error: Claude session encountered an error.")
        return []
    finally:
        await proc.wait()
        session.process_pid = None
        if proc.returncode and proc.returncode != 0:
            logger.warning(
                "Claude exited with code %d for session %s",
                proc.returncode,
                session.session_id,
            )
