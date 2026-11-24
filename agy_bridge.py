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
from typing import Optional, List, Dict, Tuple, Callable

from config import (
    AGY_LS_EXE, AGY_CLI_PATH, AGY_BRAIN_DIR, AGY_DEFAULT_MODEL,
    OUTPUT_DIR, TEMP_DIR, GEMINI_API_KEY
)

logger = logging.getLogger("AGYBridge")

MP4_REGEX = re.compile(r"([A-Za-z]:\\[^ \r\n\t\"'<>:]+\.mp4|output[\\/][^ \r\n\t\"'<>:]+\.mp4)", re.IGNORECASE)


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
            "Peak Arena tools include: download_reel, edit_reel, peak_arena_rebrand.",
            "When asked to download, rebrand, or edit videos, invoke the corresponding tools.",
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

    async def ask_agent(
        self,
        user_id: int,
        prompt: str,
        attached_files: Optional[List[Path]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
        timeout: float = 180.0
    ) -> Tuple[str, List[Path]]:
        """
        Send prompt to AGY Agent, track execution in real time, and return response + output videos.
        """
        if not self.is_available():
            raise RuntimeError(f"Neither AGY executable ({self.ls_exe}) nor CLI ({self.cli_path}) found.")

        full_prompt = self._build_contextual_prompt(user_id, prompt, attached_files)

        # Snapshot output directory before running
        OUTPUT_DIR.mkdir(exist_ok=True)
        before_videos = {p.resolve() for p in OUTPUT_DIR.glob("*.mp4")}

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

        # Detect generated videos in output folder
        after_videos = {p.resolve() for p in OUTPUT_DIR.glob("*.mp4")}
        new_videos = list(after_videos - before_videos)

        # Also search final text for video paths
        for match in MP4_REGEX.findall(final_answer):
            cand = Path(match).resolve()
            if cand.exists() and cand not in new_videos:
                new_videos.append(cand)

        # Store turn in user history
        if user_id not in self.user_histories:
            self.user_histories[user_id] = []
        self.user_histories[user_id].append({
            "user": prompt,
            "agent": final_answer
        })

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
            "ls_exe": self.ls_exe,
            "cli_path": self.cli_path,
            "active_daemons": len(active_daemons),
            "daemon_info": active_daemons[-1] if active_daemons else None,
            "active_sessions": len(self.user_conversations),
            "output_videos_count": len(list(OUTPUT_DIR.glob("*.mp4")))
        }


# Singleton instance
agy_bridge = AGYBridge()
