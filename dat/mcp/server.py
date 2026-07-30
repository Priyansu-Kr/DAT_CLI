import json
import sys
from typing import Dict, Any, List, Optional
from dat.utils.container import Container

class DATMCPServer:
    """
    MCP (Model Context Protocol) Server for Developer Automation Toolkit (DAT_CLI).
    Exposes DAT services as standard MCP tools over stdio JSON-RPC.
    """
    def __init__(self, container: Optional[Container] = None):
        self.container = container or Container.get_instance()
        self.tools = {
            "generate_document": self._tool_generate_document,
            "take_screenshot": self._tool_take_screenshot,
            "get_git_summary": self._tool_get_git_summary,
            "run_doctor": self._tool_run_doctor,
        }

    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "generate_document",
                "description": "Generates DOCX or Markdown PR/feature documentation from git branch diffs and screenshots.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "output_path": {"type": "string", "default": "doc_output.docx"},
                        "title": {"type": "string", "description": "Optional title override"},
                        "images": {"type": "array", "items": {"type": "string"}, "description": "Local screenshot paths"},
                        "capture_adb": {"type": "boolean", "default": False, "description": "Capture Android screen via ADB"},
                        "output_format": {"type": "string", "enum": ["docx", "md"], "default": "docx"}
                    }
                }
            },
            {
                "name": "take_screenshot",
                "description": "Captures screenshot from connected Android device or emulator via ADB.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "output_path": {"type": "string", "default": "screenshot.png"},
                        "device_id": {"type": "string"}
                    }
                }
            },
            {
                "name": "get_git_summary",
                "description": "Retrieves Git branch, ticket key, changed files, and diff summary for active repository.",
                "inputSchema": {"type": "object", "properties": {}}
            },
            {
                "name": "run_doctor",
                "description": "Runs environment diagnostics on DAT binary dependencies (git, adb, python-docx).",
                "inputSchema": {"type": "object", "properties": {}}
            }
        ]

    def handle_request(self, request_json: str) -> str:
        try:
            req = json.loads(request_json)
            req_id = req.get("id")
            method = req.get("method")
            params = req.get("params", {})

            if method == "tools/list":
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"tools": self.list_tools()}
                })
            elif method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments", {})
                handler = self.tools.get(tool_name)
                if not handler:
                    return json.dumps({
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32601, "message": f"Tool '{tool_name}' not found"}
                    })
                
                result_data = handler(arguments)
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"content": [{"type": "text", "text": json.dumps(result_data, indent=2)}]}
                })
            else:
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method '{method}' unsupported"}
                })
        except Exception as e:
            return json.dumps({
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32603, "message": str(e)}
            })

    def _tool_generate_document(self, args: Dict[str, Any]) -> Dict[str, Any]:
        output_file = self.container.document_service.generate_documentation(
            output_path=args.get("output_path", "doc_output.docx"),
            title_override=args.get("title"),
            image_paths=args.get("images"),
            capture_adb=args.get("capture_adb", False),
            output_format=args.get("output_format", "docx")
        )
        return {"status": "success", "file_path": output_file}

    def _tool_take_screenshot(self, args: Dict[str, Any]) -> Dict[str, Any]:
        shot_info = self.container.screenshot_service.capture_adb_screenshot(
            output_path=args.get("output_path", "screenshot.png"),
            device_id=args.get("device_id")
        )
        return {"status": "success", "file_path": shot_info.file_path}

    def _tool_get_git_summary(self, args: Dict[str, Any]) -> Dict[str, Any]:
        git_info = self.container.git_service.get_git_info()
        return {
            "branch_name": git_info.branch_name,
            "inferred_title": git_info.inferred_title,
            "ticket_id": git_info.ticket_id,
            "repo_name": git_info.repo_name,
            "changed_files_count": len(git_info.changed_files),
            "changed_files": git_info.changed_files[:10],
        }

    def _tool_run_doctor(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "is_git_repo": self.container.git_adapter.is_git_repo(),
            "adb_available": self.container.adb_adapter.is_adb_available(),
            "adb_devices": self.container.adb_adapter.get_devices(),
        }

    def run_stdio_loop(self):
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            response = self.handle_request(line)
            sys.stdout.write(response + "\n")
            sys.stdout.flush()

if __name__ == "__main__":
    server = DATMCPServer()
    server.run_stdio_loop()
