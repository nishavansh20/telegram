"""
agy_bridge.py — Antigravity (AGY) Telegram Bridge
Connects Telegram bot directly to the local Antigravity Agent runtime.
Supports:
  - Multi-turn conversation sessions per Telegram user
  - Live tool execution tracking streamed back to Telegram
  - Direct execution of Peak Arena MCP video tools (download_reel, edit_reel, peak_arena_rebrand)
  - Automatic detection and dispatch of generated .mp4 videos
  - System commands, file reading/writing, and status reporting
"""

import os
import json
import time
import asyncio
import logging
import subprocess
import re
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Callable, Any

from config import (
    AGY_LS_EXE, AGY_CLI_PATH, AGY_BRAIN_DIR, AGY_DEFAULT_MODEL,
    GEMINI_CLOUD_MODEL, GEMINI_FALLBACK_MODELS, ASSETS_DIR, OUTPUT_DIR,
    TEMP_DIR, GEMINI_API_KEY, ELEVENLABS_API_KEY
)

logger = logging.getLogger("AGYBridge")

MP4_REGEX = re.compile(
    r"([A-Za-z]:\\[^ \r\n\t\"'<>:]+\.mp4|/[^ \r\n\t\"'<>:]+\.mp4|output[\\/][^ \r\n\t\"'<>:]+\.mp4)",
    re.IGNORECASE,
)


class AGYBridge:
    def __init__(self, ls_exe: str = AGY_LS_EXE, cli_path: str = AGY_CLI_PATH, brain_dir: Path = AGY_BRAIN_DIR):
        self.ls_exe = ls_exe
        self.cli_path = cli_path
        self.brain_dir = Path(brain_dir)
        self.user_conversations: Dict[int, str] = {}
        self.user_histories: Dict[int, List[Dict[str, str]]] = {}

    def is_available(self) -> bool:
        """Check if Antigravity language_server or agentapi CLI exists."""
        return os.path.exists(self.ls_exe) or os.path.exists(self.cli_path)

    def _get_base_cmd(self) -> List[str]:
        if os.path.exists(self.ls_exe):
            return [self.ls_exe, "agentapi"]
        return [self.cli_path]

    def _prepare_env(self) -> Dict[str, str]:
        """Auto-detect running Antigravity daemon and export ANTIGRAVITY_LS_ADDRESS."""
        env = os.environ.copy()
        if not env.get("ANTIGRAVITY_LS_ADDRESS"):
            daemon_dir = Path(r"C:\Users\vansh\.gemini\antigravity\daemon")
            active_daemons = []
            if daemon_dir.exists():
                for f in daemon_dir.glob("hub_*.json"):
                    try:
                        data = json.loads(f.read_text())
                        active_daemons.append((f.stat().st_mtime, data))
                    except Exception:
                        pass
            if active_daemons:
                active_daemons.sort(key=lambda x: x[0], reverse=True)
                latest = active_daemons[0][1]
                port = latest.get("httpPort")
                token = latest.get("csrfToken", "")
                if port:
                    env["ANTIGRAVITY_LS_ADDRESS"] = f"localhost:{port}"
                    os.environ["ANTIGRAVITY_LS_ADDRESS"] = f"localhost:{port}"
                if token:
                    env["ANTIGRAVITY_CSRF_TOKEN"] = token
                    os.environ["ANTIGRAVITY_CSRF_TOKEN"] = token
                env["ANTIGRAVITY_APP_DATA_DIR"] = r"C:/Users/vansh/.gemini/antigravity"
                os.environ["ANTIGRAVITY_APP_DATA_DIR"] = r"C:/Users/vansh/.gemini/antigravity"
        return env

    def reset_user(self, user_id: int):
        """Reset conversation context for a user."""
        self.user_conversations.pop(user_id, None)
        self.user_histories.pop(user_id, None)

    def _build_contextual_prompt(self, user_id: int, current_prompt: str, attached_files: Optional[List[Path]] = None) -> str:
        """Construct prompt with system context, file attachments, and short history."""
        parts = [
            f"[Telegram Remote Client | User ID: {user_id} | Workspace: Peak-Arena-Reel-Automation]",
            "You are the remote Antigravity (AGY) Agent for the Peak Arena Reel Automation system.",
            "You have direct access to tools for video editing, file management, and terminal execution.",
            "Peak Arena tools include: download_reel, edit_reel, peak_arena_rebrand, replace_default_asset.",
            "When asked to replace default bot images (logo, app overlay, bio outro) or edit videos, invoke the tools directly.",
            "Keep Telegram responses helpful, concise, and formatted in clean markdown.",
            ""
        ]

        # Add recent conversation turns (last 3)
        history = self.user_histories.get(user_id, [])
        if history:
            parts.append("Recent conversation:")
            for turn in history[-3:]:
                parts.append(f"User: {turn['user']}")
                parts.append(f"Agent: {turn['agent']}")
            parts.append("")

        # Add attached files info
        if attached_files:
            parts.append("Attached local files from Telegram:")
            for f in attached_files:
                parts.append(f"- {f.resolve()}")
            parts.append("")

        parts.append(f"User Request: {current_prompt}")
        return "\n".join(parts)

    def _collect_new_videos(self, before_videos: set, final_answer: str) -> List[Path]:
        after_videos = {p.resolve() for p in OUTPUT_DIR.glob("*.mp4")}
        new_videos = list(after_videos - before_videos)
        for match in MP4_REGEX.findall(final_answer):
            cand = Path(match).resolve()
            if cand.exists() and cand not in new_videos:
                new_videos.append(cand)
        return new_videos

    def _record_history(self, user_id: int, prompt: str, answer: str):
        self.user_histories.setdefault(user_id, []).append({
            "user": prompt,
            "agent": answer,
        })

    async def ask_agent(
        self,
        user_id: int,
        prompt: str,
        attached_files: Optional[List[Path]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
        timeout: float = 180.0
    ) -> Tuple[str, List[Path]]:
        """
        Route prompt to local Antigravity Agent if available, else Gemini Cloud (Hydrogen).
        """
        OUTPUT_DIR.mkdir(exist_ok=True)
        before_videos = {p.resolve() for p in OUTPUT_DIR.glob("*.mp4")}

        if self.is_available():
            try:
                return await self._ask_local_agy(
                    user_id, prompt, attached_files, status_callback, timeout, before_videos
                )
            except Exception as e:
                if not GEMINI_API_KEY:
                    raise
                logger.warning(f"Local AGY failed ({e}), falling back to Gemini Cloud ({GEMINI_CLOUD_MODEL})")

        if GEMINI_API_KEY:
            return await self._ask_gemini_cloud(
                user_id, prompt, attached_files, status_callback, before_videos
            )

        raise RuntimeError(
            f"Neither local AGY runtime ({self.ls_exe}) nor GEMINI_API_KEY is available."
        )

    async def _ask_local_agy(
        self,
        user_id: int,
        prompt: str,
        attached_files: Optional[List[Path]],
        status_callback: Optional[Callable[[str], None]],
        timeout: float,
        before_videos: set,
    ) -> Tuple[str, List[Path]]:
        full_prompt = self._build_contextual_prompt(user_id, prompt, attached_files)

        if status_callback:
            status_callback("⚡ <b>Antigravity Agent initializing...</b>")

        # Launch AGY new-conversation
        title = f"Telegram User {user_id}"
        cmd = self._get_base_cmd() + ["new-conversation", f"--title={title}"]
        if AGY_DEFAULT_MODEL:
            cmd.append(f"--model={AGY_DEFAULT_MODEL}")
        cmd.append(full_prompt)

        env = self._prepare_env()
        logger.info(f"Spawning AGY agent for user {user_id} (LS_ADDR: {env.get('ANTIGRAVITY_LS_ADDRESS')})...")
        proc = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, check=False, env=env
        )

        if proc.returncode != 0:
            err = proc.stderr.strip() or proc.stdout.strip()
            raise RuntimeError(f"AGY launch error (exit code {proc.returncode}): {err}")

        # Parse conversation ID
        conv_id = None
        try:
            res_json = json.loads(proc.stdout)
            conv_id = res_json.get("response", {}).get("newConversation", {}).get("conversationId")
        except Exception as e:
            logger.error(f"Failed to parse AGY response JSON: {proc.stdout} ({e})")

        if not conv_id:
            m = re.search(r"([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})", proc.stdout)
            if m:
                conv_id = m.group(1)

        if not conv_id:
            raise RuntimeError(f"Could not retrieve conversationId from AGY: {proc.stdout}")

        self.user_conversations[user_id] = conv_id
        logger.info(f"AGY Conversation ID: {conv_id}")

        transcript_path = self.brain_dir / conv_id / ".system_generated" / "logs" / "transcript.jsonl"

        # Poll transcript.jsonl
        start_time = time.time()
        final_answer = ""
        seen_tools = set()

        while time.time() - start_time < timeout:
            await asyncio.sleep(0.7)
            if not transcript_path.exists():
                continue

            try:
                content = await asyncio.to_thread(transcript_path.read_text, "utf-8")
                lines = [json.loads(line) for line in content.splitlines() if line.strip()]
            except Exception:
                continue

            for entry in lines:
                step_idx = entry.get("step_index", 0)
                entry_type = entry.get("type")
                entry_status = entry.get("status")
                tool_calls = entry.get("tool_calls", [])

                # Report any tool calls to Telegram
                if tool_calls:
                    for tc in tool_calls:
                        t_name = tc.get("name", "tool")
                        tool_key = f"{step_idx}_{t_name}"
                        if tool_key not in seen_tools:
                            seen_tools.add(tool_key)
                            if status_callback:
                                status_callback(f"⚙️ <b>AGY Action:</b> <code>{t_name}</code>")

                # Check if final planner response arrived
                if entry_type == "PLANNER_RESPONSE" and entry_status == "DONE":
                    entry_content = (entry.get("content") or "").strip()
                    if entry_content and not tool_calls:
                        final_answer = entry_content

            # When we have a final answer, wait briefly to verify no new steps were spawned
            if final_answer:
                await asyncio.sleep(0.8)
                try:
                    content = await asyncio.to_thread(transcript_path.read_text, "utf-8")
                    lines = [json.loads(line) for line in content.splitlines() if line.strip()]
                    last_entry = lines[-1] if lines else {}
                    # If last entry has tools, keep waiting
                    if last_entry.get("tool_calls"):
                        final_answer = ""
                        continue
                    if last_entry.get("type") == "PLANNER_RESPONSE":
                        final_answer = (last_entry.get("content") or final_answer).strip()
                        break
                except Exception:
                    break

        if not final_answer:
            final_answer = "⚠️ Antigravity agent completed execution without text response."

        new_videos = self._collect_new_videos(before_videos, final_answer)
        self._record_history(user_id, prompt, final_answer)
        return final_answer, new_videos

    async def _ask_gemini_cloud(
        self,
        user_id: int,
        prompt: str,
        attached_files: Optional[List[Path]],
        status_callback: Optional[Callable[[str], None]],
        before_videos: set,
    ) -> Tuple[str, List[Path]]:
        """Cloud agent fallback via google-genai with manual single-run tool dispatch."""
        from google import genai
        from google.genai import types
        from video_processor import download_media, apply_edit_instructions, process_reel, update_default_asset
        from prompt_parser import parse_edit_prompt, assign_images_to_instructions

        if status_callback:
            status_callback(f"☁️ <b>Gemini Cloud ({GEMINI_CLOUD_MODEL}) thinking...</b>")

        def notify(msg: str):
            if status_callback:
                status_callback(msg)

        def replace_default_asset(source_image_path: str, target_asset: str) -> str:
            """Update a default bot image in assets/ directory. target_asset must be one of: logo.png, app_overlay_framed.png, app_screen_clean.png, insta_bio_outro.png (or reset_bio)."""
            notify(f"⚙️ <b>Action:</b> <code>replace_default_asset({target_asset})</code>")
            return json.dumps(update_default_asset(source_image_path, target_asset))

        def download_reel(url: str) -> str:
            """Download an Instagram Reel or YouTube Short from a URL and return the local video path."""
            notify("⚙️ <b>Action:</b> <code>download_reel</code>")
            TEMP_DIR.mkdir(exist_ok=True)
            path = download_media(url)
            return json.dumps({"video_path": str(path), "status": "downloaded"})

        def edit_reel(video_path: str, edit_prompt: str, images: Optional[List[str]] = None) -> str:
            """Edit a local video using natural-language edit instructions (replace app screen, logo, bio, voiceover, text overlay, mute, extend)."""
            notify("⚙️ <b>Action:</b> <code>edit_reel</code>")
            video = Path(video_path)
            if not video.exists():
                return json.dumps({"error": f"video_path not found: {video_path}"})
            img_list = images or []
            instructions = parse_edit_prompt(edit_prompt, img_list, GEMINI_API_KEY)
            if not instructions:
                return json.dumps({"error": "Could not parse any edit instructions from prompt."})
            assign_images_to_instructions(instructions, [Path(p) for p in img_list])
            output = apply_edit_instructions(video, instructions)
            return json.dumps({"output_path": str(output), "ops_applied": len(instructions), "status": "done"})

        def peak_arena_rebrand(video_path: str, insta_handle: str = "@_maxeddd") -> str:
            """Apply the full automated Peak Arena rebrand (app overlay, shield logo, bio outro) to a video."""
            notify("⚙️ <b>Action:</b> <code>peak_arena_rebrand</code>")
            video = Path(video_path)
            if not video.exists():
                return json.dumps({"error": f"video_path not found: {video_path}"})
            output = process_reel(
                video_path=video,
                replace_bio=True,
                insta_handle=insta_handle,
                elevenlabs_api_key=ELEVENLABS_API_KEY,
            )
            return json.dumps({"output_path": str(output), "status": "done"})

        def list_workspace_files() -> str:
            """List files currently in output/, assets/, and temp/ directories."""
            notify("⚙️ <b>Action:</b> <code>list_workspace_files</code>")
            data = {}
            for name, folder in [("output", OUTPUT_DIR), ("assets", ASSETS_DIR), ("temp", TEMP_DIR)]:
                data[name] = [str(p.name) for p in sorted(folder.glob("*"))[:30]] if folder.exists() else []
            return json.dumps(data)

        system_inst = (
            "You are the Peak Arena Cloud Agent running over Telegram.\n"
            "Tools available: download_reel, edit_reel, peak_arena_rebrand, replace_default_asset, list_workspace_files.\n"
            "If the user uploads images and asks to update default bot pics in assets/, call replace_default_asset for each target (logo.png, app_overlay_framed.png, app_screen_clean.png, insta_bio_outro.png), then run peak_arena_rebrand or edit_reel if requested.\n"
            "When asked to download, rebrand, or edit videos, invoke the tools directly and report the exact output path.\n"
            "Keep replies concise and readable on mobile Telegram."
        )

        # Build contents list (recent history text + current request + attached image bytes)
        history_lines = []
        for turn in self.user_histories.get(user_id, [])[-4:]:
            history_lines.append(f"User: {turn['user']}\nAgent: {turn['agent']}")
        ctx_text = ""
        if history_lines:
            ctx_text += "Recent conversation:\n" + "\n".join(history_lines) + "\n\n"
        if attached_files:
            ctx_text += "Attached local files:\n" + "\n".join(f"- {f.resolve()}" for f in attached_files) + "\n\n"
        ctx_text += f"User Request: {prompt}"

        user_parts: List[Any] = [types.Part.from_text(text=ctx_text)]
        for f in (attached_files or []):
            if f.exists() and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                mime = "image/png" if f.suffix.lower() == ".png" else "image/jpeg"
                user_parts.append(types.Part.from_bytes(data=f.read_bytes(), mime_type=mime))

        tool_map = {
            "download_reel": download_reel,
            "edit_reel": edit_reel,
            "peak_arena_rebrand": peak_arena_rebrand,
            "replace_default_asset": replace_default_asset,
            "list_workspace_files": list_workspace_files,
        }

        def _invoke_cloud() -> str:
            client = genai.Client(
                api_key=GEMINI_API_KEY,
                http_options=types.HttpOptions(
                    timeout=18000,
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
            cfg = types.GenerateContentConfig(
                system_instruction=system_inst,
                tools=list(tool_map.values()),
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            )
            active_candidates = list(dict.fromkeys(m for m in (GEMINI_CLOUD_MODEL, *GEMINI_FALLBACK_MODELS) if m))
            history: List[Any] = [types.Content(role="user", parts=user_parts)]
            completed_tools: List[str] = []
            last_err: Optional[Exception] = None

            for _step in range(6):
                resp = None
                for model_name in list(active_candidates):
                    try:
                        resp = client.models.generate_content(
                            model=model_name,
                            contents=history,
                            config=cfg,
                        )
                        if resp and (resp.function_calls or (resp.text and resp.text.strip())):
                            if active_candidates[0] != model_name:
                                active_candidates.remove(model_name)
                                active_candidates.insert(0, model_name)
                            break
                        resp = None
                    except Exception as err:
                        last_err = err
                        err_str = str(err)
                        if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "404" in err_str:
                            if model_name in active_candidates:
                                active_candidates.remove(model_name)
                        logger.warning(f"Cloud model {model_name} failed ({err}), trying next...")
                        resp = None

                if resp is None:
                    if completed_tools:
                        return "Done (cloud summary unavailable):\n" + "\n".join(completed_tools)
                    raise RuntimeError(f"All cloud Gemini models failed: {last_err}")

                if not resp.function_calls:
                    return (resp.text or "").strip()

                if resp.candidates and resp.candidates[0].content:
                    history.append(resp.candidates[0].content)

                response_parts = []
                for fc in resp.function_calls:
                    fn = tool_map.get(fc.name)
                    if fn is None:
                        res_payload = {"error": f"Unknown tool: {fc.name}"}
                    else:
                        try:
                            args = dict(fc.args or {})
                            res_str = fn(**args)
                            completed_tools.append(f"{fc.name}: {res_str}")
                            res_payload = {"result": res_str}
                        except Exception as tool_err:
                            logger.warning(f"Cloud tool {fc.name} error: {tool_err}")
                            res_payload = {"error": str(tool_err)}
                    response_parts.append(
                        types.Part.from_function_response(name=fc.name, response=res_payload)
                    )
                history.append(types.Content(role="user", parts=response_parts))

            return "\n".join(completed_tools) or "Done."

        final_answer = await asyncio.to_thread(_invoke_cloud)
        new_videos = self._collect_new_videos(before_videos, final_answer)
        self._record_history(user_id, prompt, final_answer)
        return final_answer, new_videos

    def get_status(self) -> Dict[str, any]:
        """Return AGY system and bridge health status."""
        daemon_dir = Path(r"C:\Users\vansh\.gemini\antigravity\daemon")
        active_daemons = []
        if daemon_dir.exists():
            for f in daemon_dir.glob("hub_*.json"):
                try:
                    active_daemons.append(json.loads(f.read_text()))
                except Exception:
                    pass

        return {
            "cli_available": self.is_available(),
            "cloud_available": bool(GEMINI_API_KEY),
            "model": AGY_DEFAULT_MODEL if self.is_available() else GEMINI_CLOUD_MODEL,
            "cloud_model": GEMINI_CLOUD_MODEL,
            "ls_exe": self.ls_exe,
            "cli_path": self.cli_path,
            "active_daemons": len(active_daemons),
            "daemon_info": active_daemons[-1] if active_daemons else None,
            "active_sessions": len(self.user_conversations),
            "output_videos_count": len(list(OUTPUT_DIR.glob("*.mp4")))
        }


# Singleton instance
agy_bridge = AGYBridge()
