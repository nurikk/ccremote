"""Message relay — single session, DM, sendMessageDraft streaming."""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ccremote.bot import send_draft, send_message
from ccremote.config import Configuration, save_session_id
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
                        tool_uses.append(
                            {
                                "name": name,
                                "id": block.get("id", ""),
                                "input": block.get("input", {}),
                            }
                        )
            return {"type": "assistant", "text": "\n".join(text_parts), "tool_uses": tool_uses}
        case {"type": "user", "message": {"content": list(content)}}:
            results = []
            for block in content:
                match block:
                    case {"type": "tool_result", "tool_use_id": str(tid)}:
                        results.append(
                            {
                                "tool_use_id": tid,
                                "content": str(block.get("content", ""))[:200],
                            }
                        )
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
                "permission_denials": event.get("permission_denials", []),
            }
        case _:
            return {"type": "unknown"}


def _parse_stream_event(inner: dict) -> dict:
    match inner:
        case {
            "type": "content_block_start",
            "content_block": {"type": "tool_use", "name": str(name)},
        }:
            return {"type": "tool_start", "name": name, "id": inner["content_block"].get("id", "")}
        case {"type": "content_block_start", "content_block": {"type": "thinking"}}:
            return {"type": "thinking_start"}
        case {"type": "content_block_start", "content_block": dict(block)}:
            return {"type": "block_start", "block_type": block.get("type", "")}
        case {"type": "content_block_delta", "delta": {"type": "text_delta", "text": str(t)}}:
            return {"type": "text_delta", "text": t}
        case {
            "type": "content_block_delta",
            "delta": {"type": "input_json_delta", "partial_json": str(j)},
        }:
            return {"type": "input_delta", "json": j}
        case {
            "type": "content_block_delta",
            "delta": {"type": "thinking_delta", "thinking": str(t)},
        }:
            return {"type": "thinking_delta", "text": t}
        case {"type": "content_block_delta"}:
            return {"type": "delta_other"}
        case {"type": "content_block_stop"}:
            return {"type": "block_stop"}
        case {"type": str(t)} if t in ("message_start", "message_delta", "message_stop"):
            return {"type": t}
        case _:
            return {"type": "stream_other"}



# ── Draft builder ──────────────────────────────────────────────────


class DraftBuilder:
    """Builds streaming draft text from Claude events."""

    def __init__(self, max_length: int = 4000) -> None:
        self.max_length = max_length
        self.response_text = ""
        self.thinking_text = ""
        self.active_tool: str | None = None
        self.tool_input_json = ""
        self.tool_log: deque[str] = deque(maxlen=5)
        self.is_thinking = False
        self.permission_denials: list[dict] = []
        self._quiet_tools = frozenset(("Read", "Edit", "Grep", "Glob", "ToolSearch"))
        self._last_tool: str | None = None

    def process(self, parsed: dict) -> None:
        match parsed:
            case {"type": "text_delta", "text": str(t)}:
                self.response_text += t
            case {"type": "thinking_start"}:
                self.is_thinking = True
                self.thinking_text = ""
                logger.info("Thinking...")
            case {"type": "thinking_delta", "text": str(t)}:
                self.thinking_text += t
            case {"type": "tool_start", "name": str(name)}:
                self.active_tool = name
                self.tool_input_json = ""
                logger.info("Tool start: %s", name)
            case {"type": "input_delta", "json": str(j)}:
                self.tool_input_json += j
            case {"type": "block_stop"}:
                if self.active_tool:
                    summary = self._format_tool_summary()
                    self.tool_log.append(summary)
                    logger.info("Tool done: %s", summary)
                    self._last_tool = self.active_tool
                    self.active_tool = None
                    self.tool_input_json = ""
                if self.is_thinking:
                    self.is_thinking = False
            case {"type": "tool_result"}:
                results = parsed.get("results", [])
                duration = parsed.get("duration_ms")
                for r in results:
                    content = r.get("content", "")[:200]
                    logger.info("Tool result: %s", content[:200])
                if self._last_tool not in self._quiet_tools:
                    for r in results:
                        line = f"  ↳ {r.get('content', '')[:100]}"
                        if duration:
                            line += f" ({duration}ms)"
                        self.tool_log.append(line)
                    for f in parsed.get("filenames", [])[:3]:
                        self.tool_log.append(f"  📄 {f}")
            case {"type": "assistant", "text": str(t)} if t:
                self.response_text = t
            case {"type": "api_retry"}:
                logger.warning(
                    "API retry #%s: %s", parsed.get("attempt", 0), parsed.get("error", "")
                )
                self.tool_log.append(
                    f"⚠️ Retry #{parsed.get('attempt', 0)}: {parsed.get('error', '')}"
                )
            case {"type": "result"}:
                text = parsed.get("text", "")
                if text:
                    self.response_text = text
                self.permission_denials = parsed.get("permission_denials", [])
                logger.info("Result: denials=%d", len(self.permission_denials))

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
            parts.append("\n".join(self.tool_log))
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
        return text[: self.max_length]


def deduplicate_denials(denials: list[dict]) -> tuple[list[str], list[str]]:
    """Extract unique tool names and detail lines from permission denials.

    Returns (denied_tools, denied_details) with duplicates removed.
    """
    denied_tools = list({d.get("tool_name", "") for d in denials if d.get("tool_name")})
    seen: set[str] = set()
    denied_details: list[str] = []
    for d in denials:
        tool = d.get("tool_name", "")
        inp = d.get("tool_input", {})
        if isinstance(inp, dict):
            detail = inp.get("command") or inp.get("file_path") or ""
        else:
            detail = str(inp)[:80]
        entry = f"{tool}: {detail}" if detail else tool
        if entry not in seen:
            seen.add(entry)
            denied_details.append(entry)
    return denied_tools, denied_details


# ── Handlers ───────────────────────────────────────────────────────


async def download_attachment(bot: Bot, message: Message, work_dir: str) -> Path | None:
    """Download a photo or document from the message to the working directory."""
    attachments_dir = Path(work_dir) / ".ccremote-attachments"
    attachments_dir.mkdir(exist_ok=True)

    try:
        if message.photo:
            photo = message.photo[-1]  # largest size
            file = await bot.get_file(photo.file_id)
            if not file.file_path:
                return None
            ext = Path(file.file_path).suffix or ".jpg"
            dest = attachments_dir / f"{photo.file_unique_id}{ext}"
            await bot.download_file(file.file_path, dest)
            return dest

        if message.document:
            file = await bot.get_file(message.document.file_id)
            if not file.file_path:
                return None
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
        voice = message.voice
        if not voice:
            return None
        file = await bot.get_file(voice.file_id)
        if not file.file_path:
            return None
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            await bot.download_file(file.file_path, tmp_path)

        form = aiohttp.FormData()
        form.add_field("model", "whisper-1")
        with open(tmp_path, "rb") as audio_file:
            form.add_field(
                "file",
                audio_file,
                filename="voice.ogg",
                content_type="audio/ogg",
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
        logger.info("Transcribed voice (%ds): %s", voice.duration, text[:80])
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
    # Store pending retries: callback_id -> (prompt, denied_tools)
    pending_retries: dict[str, tuple[str, list[str]]] = {}

    @dp.message()
    async def handle_dm(message: Message) -> None:
        text = message.text or message.caption or ""

        if message.voice:
            if not config.openai_api_key:
                await message.reply(
                    "Voice messages are not enabled.\n"
                    "Set <code>CCREMOTE_OPENAI_API_KEY</code> to your OpenAI API key "
                    "as an environment variable or in your <code>.ccremote</code> file.",
                    parse_mode="HTML",
                )
                return
            transcription = await transcribe_voice(bot, message, config)
            if transcription:
                text = transcription

        if message.photo or message.document:
            path = await download_attachment(bot, message, session.working_directory)
            if path:
                if text:
                    text = f"{text}\n\n[User sent you a file: {path}]".strip()
                else:
                    text = f"User sent you a file: {path}"

        if not text:
            return

        user_id = message.from_user.id if message.from_user else 0

        cmd = text.strip().lower()
        if cmd in ("/new", "/clear"):
            session.claude_session_id = ""
            save_session_id(session.working_directory, "")
            logger.info("Session cleared by user %s", user_id)
            await send_message(bot, message.chat.id, "Session cleared.")
            return

        if cmd == "/start":
            text = (
                "Briefly describe: what project is this, what directory you're in, "
                "and what you're ready to help with."
            )

        logger.info("DM from %s → session %s", user_id, session.session_id[:8])

        session.last_message_at = datetime.now(UTC)

        task = asyncio.create_task(_run_relay(text, message.chat.id))
        task.add_done_callback(lambda t: t.result() if not t.cancelled() else None)

    async def _run_relay(
        prompt: str,
        chat_id: int,
        allowed_tools: list[str] | None = None,
    ) -> None:
        await relay_prompt_to_claude(
            prompt,
            session,
            chat_id,
            bot,
            config,
            allowed_tools=allowed_tools,
            pending_retries=pending_retries,
        )

    @dp.callback_query(lambda c: c.data and c.data.startswith("perm_"))
    async def handle_permission_callback(callback: CallbackQuery) -> None:
        if not callback.data:
            return
        callback_id, action = callback.data.rsplit(":", 1)

        if callback_id not in pending_retries:
            await callback.answer("Expired")
            return

        prompt, denied_tools = pending_retries.pop(callback_id)
        msg = callback.message

        if action == "allow":
            await callback.answer("Allowed")
            if isinstance(msg, Message):
                await msg.edit_text(f"✅ Allowed: {', '.join(denied_tools)}")
                task = asyncio.create_task(
                    _run_relay(prompt, msg.chat.id, allowed_tools=denied_tools)
                )
                task.add_done_callback(lambda t: t.result() if not t.cancelled() else None)
        else:
            await callback.answer("Skipped")
            if isinstance(msg, Message):
                await msg.edit_text("⏭ Skipped permission request.")


async def relay_prompt_to_claude(
    prompt: str,
    session: Session,
    chat_id: int,
    bot: Bot,
    config: Configuration,
    allowed_tools: list[str] | None = None,
    pending_retries: dict[str, tuple[str, list[str]]] | None = None,
) -> None:
    """Spawn claude --print and stream output via sendMessageDraft."""
    logger.info("Relaying to claude session %s: %s", session.session_id[:8], prompt[:80])

    args = [
        "claude",
        "--print",
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

    args.extend(["--", prompt])

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
        return

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
                    save_session_id(session.working_directory, new_sid)
                continue

            draft.process(parsed)

            now = time.monotonic()
            if now - last_draft_time >= throttle_s:
                draft_text = draft.build_draft()
                if draft_text:
                    await send_draft(bot, chat_id, draft_text, draft_id)
                    last_draft_time = now

        final_text = draft.build_final()
        logger.info("Sending to user: %s", final_text[:200])
        await send_message(bot, chat_id, final_text)

        if draft.permission_denials and pending_retries is not None:
            denied_tools, denied_details = deduplicate_denials(draft.permission_denials)
            callback_id = f"perm_{hash(prompt + str(time.monotonic())) & 0xFFFFFF:06x}"
            pending_retries[callback_id] = (prompt, denied_tools)

            tools_desc = "\n".join(f"  • {d}" for d in denied_details)
            kb = InlineKeyboardBuilder()
            kb.button(text="✅ Allow", callback_data=f"{callback_id}:allow")
            kb.button(text="❌ Skip", callback_data=f"{callback_id}:skip")
            kb.adjust(2)

            await send_message(
                bot, chat_id, f"⚠️ Permission denied:\n{tools_desc}", reply_markup=kb.as_markup()
            )

    except Exception:
        logger.exception("Error during relay for session %s", session.session_id)
        await send_message(bot, chat_id, "Error: Claude session encountered an error.")
    finally:
        await proc.wait()
        session.process_pid = None
        if proc.returncode and proc.returncode != 0:
            stderr = await proc.stderr.read() if proc.stderr else b""
            logger.warning(
                "Claude exited with code %d for session %s: %s",
                proc.returncode,
                session.session_id,
                stderr.decode(errors="replace").strip()[:500],
            )
