#!/usr/bin/env python3
import json
import mimetypes
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from operations import (
    adjust_item,
    adjust_green_item,
    create_brew_record,
    create_bean_batch,
    create_cupping_record,
    create_green_item,
    create_item,
    create_roast,
    create_roast_for_bean_batch,
    deduct_item,
    deduct_green_item,
    delete_brew_record,
    delete_green_item,
    delete_item,
    fetch_brew_records,
    fetch_bean_batches,
    fetch_green_inventory,
    fetch_inventory,
    fetch_roast_compare,
    fetch_roasts,
    get_bean_batch,
    get_roast,
    update_brew_record,
    update_green_item,
    update_item,
    update_roast,
    update_roast_learning_note,
)
from tastings import ARCHIVES, TastingConflict, add_person, save_feedback, workspace
from schema import init_db
from ui import INDEX_HTML
from xbloom_bridge.protocol import MAX_RECIPE_BYTES
from xbloom_recipes import RecipeStore, preview_recipe


HOST = "0.0.0.0"
PORT = 8000
STATIC_DIR = Path(__file__).resolve().parent / "static"


class RecipeRequestError(ValueError):
    def __init__(self, message, status=HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.status = status


class CoffeeInventoryHandler(BaseHTTPRequestHandler):
    recipe_store = RecipeStore(Path(__file__).resolve().parent / "recipes")

    def do_GET(self):
        parsed = urlparse(self.path)
        archive = re.fullmatch(r"/api/tastings/source/(BREW_RECORD_\d{4}-\d{2}-\d{2}_[A-Z0-9_-]+)", parsed.path)
        if archive:
            path = ARCHIVES / (archive[1] + ".md")
            if not path.is_file() or path.is_symlink():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            raw = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if parsed.path == "/api/tastings":
            self._send_json(workspace())
            return
        if parsed.path in ("/xb-recipes", "/tastings"):
            self._send_html(INDEX_HTML)
            return
        if parsed.path == "/api/xb-recipes" or parsed.path.startswith("/api/xb-recipes/"):
            self._xb_recipe_get(parsed.path)
            return
        if parsed.path.startswith("/static/"):
            self._send_static(parsed.path)
            return

        if parsed.path == "/":
            self._send_html(INDEX_HTML)
            return

        if parsed.path == "/brews":
            self._send_html(INDEX_HTML)
            return

        if parsed.path == "/green":
            self._send_html(INDEX_HTML)
            return

        if parsed.path in {"/roasts", "/roasts/new", "/roasts/compare"}:
            self._send_html(INDEX_HTML)
            return

        if parsed.path.startswith("/roasts/"):
            self._send_html(INDEX_HTML)
            return

        if parsed.path.startswith("/beans/"):
            self._send_html(INDEX_HTML)
            return

        if parsed.path == "/api/inventory":
            self._send_json(fetch_inventory())
            return

        if parsed.path == "/api/green-inventory":
            self._send_json(fetch_green_inventory())
            return

        if parsed.path == "/api/bean-batches":
            self._send_json(fetch_bean_batches())
            return

        if parsed.path.startswith("/api/bean-batches/"):
            try:
                batch_id = self._extract_bean_batch_id(parsed.path, "")
                self._send_json(get_bean_batch(batch_id))
            except KeyError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if parsed.path == "/api/roasts":
            self._send_json(fetch_roasts())
            return

        if parsed.path == "/api/roasts/compare":
            try:
                query = parse_qs(parsed.query)
                self._send_json(fetch_roast_compare(query.get("ids", [""])[0].split(",")))
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if parsed.path.startswith("/api/roasts/"):
            try:
                roast_id = self._extract_roast_id(parsed.path, "")
                self._send_json(get_roast(roast_id))
            except KeyError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if parsed.path == "/api/brews":
            self._send_json(fetch_brew_records())
            return

        self._send_json({"error": "Not Found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/api/tastings/people", "/api/tastings/feedback"):
            self.close_connection = True
            try:
                data = json.loads(self._read_xb_recipe_body().decode("utf-8"))
                if parsed.path.endswith("/people"):
                    self._send_json(add_person(data), HTTPStatus.CREATED)
                else:
                    self._send_json(save_feedback(data))
            except RecipeRequestError as exc:
                self._send_json({"error": str(exc).replace("配方", "品饮")}, exc.status)
            except TastingConflict as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.CONFLICT)
            except KeyError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
            except (ValueError, RecursionError) as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/xb-recipes" or parsed.path.startswith("/api/xb-recipes/"):
            self._xb_recipe_post(parsed.path)
            return
        try:
            data = self._read_json()

            if parsed.path == "/api/inventory":
                item = create_item(data)
                self._send_json({"item": item}, status=HTTPStatus.CREATED)
                return

            if parsed.path == "/api/brews":
                item = create_brew_record(data)
                self._send_json({"item": item}, status=HTTPStatus.CREATED)
                return

            if parsed.path == "/api/green-inventory":
                item = create_green_item(data)
                self._send_json({"item": item}, status=HTTPStatus.CREATED)
                return

            if parsed.path == "/api/bean-batches":
                item = create_bean_batch(data)
                self._send_json({"item": item}, status=HTTPStatus.CREATED)
                return

            if parsed.path.startswith("/api/bean-batches/") and parsed.path.endswith("/roasts"):
                batch_id = self._extract_bean_batch_id(parsed.path, "/roasts")
                item = create_roast_for_bean_batch(batch_id, data)
                self._send_json({"item": item}, status=HTTPStatus.CREATED)
                return

            if parsed.path == "/api/roasts":
                item = create_roast(data)
                self._send_json({"item": item}, status=HTTPStatus.CREATED)
                return

            if parsed.path.startswith("/api/roasts/") and parsed.path.endswith("/cupping"):
                roast_id = self._extract_roast_id(parsed.path, "/cupping")
                item = create_cupping_record(roast_id, data)
                self._send_json({"item": item}, status=HTTPStatus.CREATED)
                return

            if parsed.path.startswith("/api/inventory/") and parsed.path.endswith("/add"):
                item_id = self._extract_item_id(parsed.path, "/add")
                item = adjust_item(item_id, data.get("net_weight"), data.get("price_total"))
                self._send_json({"item": item})
                return

            if parsed.path.startswith("/api/inventory/") and parsed.path.endswith("/deduct"):
                item_id = self._extract_item_id(parsed.path, "/deduct")
                item = deduct_item(item_id, data.get("net_weight"), data.get("price_total"))
                self._send_json({"item": item})
                return

            if parsed.path.startswith("/api/green-inventory/") and parsed.path.endswith("/add"):
                item_id = self._extract_green_item_id(parsed.path, "/add")
                item = adjust_green_item(item_id, data.get("total_weight"))
                self._send_json({"item": item})
                return

            if parsed.path.startswith("/api/green-inventory/") and parsed.path.endswith("/deduct"):
                item_id = self._extract_green_item_id(parsed.path, "/deduct")
                item = deduct_green_item(item_id, data.get("total_weight"))
                self._send_json({"item": item})
                return

            self._send_json({"error": "Not Found"}, status=HTTPStatus.NOT_FOUND)
        except KeyError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except json.JSONDecodeError:
            self._send_json({"error": "请求体必须是合法 JSON"}, status=HTTPStatus.BAD_REQUEST)

    def do_PUT(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path.startswith("/api/inventory/"):
                item_id = self._extract_item_id(parsed.path, "")
                data = self._read_json()
                item = update_item(item_id, data)
                self._send_json({"item": item})
                return
            if parsed.path.startswith("/api/green-inventory/"):
                item_id = self._extract_green_item_id(parsed.path, "")
                data = self._read_json()
                item = update_green_item(item_id, data)
                self._send_json({"item": item})
                return
            if parsed.path.startswith("/api/roasts/") and parsed.path.endswith("/learning-note"):
                roast_id = self._extract_roast_id(parsed.path, "/learning-note")
                data = self._read_json()
                item = update_roast_learning_note(roast_id, data)
                self._send_json({"item": item})
                return
            if parsed.path.startswith("/api/roasts/"):
                roast_id = self._extract_roast_id(parsed.path, "")
                data = self._read_json()
                item = update_roast(roast_id, data)
                self._send_json({"item": item})
                return
            if parsed.path.startswith("/api/brews/"):
                record_id = self._extract_record_id(parsed.path)
                data = self._read_json()
                item = update_brew_record(record_id, data)
                self._send_json({"item": item})
                return
            self._send_json({"error": "Not Found"}, status=HTTPStatus.NOT_FOUND)
        except KeyError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except json.JSONDecodeError:
            self._send_json({"error": "请求体必须是合法 JSON"}, status=HTTPStatus.BAD_REQUEST)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path.startswith("/api/inventory/"):
                item_id = self._extract_item_id(parsed.path, "")
                delete_item(item_id)
                self._send_json({"ok": True})
                return
            if parsed.path.startswith("/api/green-inventory/"):
                item_id = self._extract_green_item_id(parsed.path, "")
                delete_green_item(item_id)
                self._send_json({"ok": True})
                return
            if parsed.path.startswith("/api/brews/"):
                record_id = self._extract_record_id(parsed.path)
                delete_brew_record(record_id)
                self._send_json({"ok": True})
                return
            self._send_json({"error": "Not Found"}, status=HTTPStatus.NOT_FOUND)
        except KeyError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def log_message(self, fmt, *args):
        return

    def _xb_recipe_get(self, path):
        try:
            if path == "/api/xb-recipes":
                self._send_json(self.recipe_store.list())
            else:
                name = unquote(path[len("/api/xb-recipes/"):])
                if name.endswith("/download"):
                    name = name[:-len("/download")]
                    body = self.recipe_store.download(name)
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Disposition", "attachment; filename=recipe.json; filename*=UTF-8''" + quote(name + ".recipe.json", safe=""))
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self._send_json({"item": self.recipe_store.get(name)})
        except FileNotFoundError:
            self._send_json({"error": "配方不存在"}, status=HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except OSError:
            self._send_json({"error": "无法读取配方，请检查文件权限或配方目录"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _read_xb_recipe_body(self):
        # This boundary retains raw JSON: parsing it with _read_json first would
        # erase duplicate keys and round numeric tokens before strict validation.
        if self.headers.get_all("Transfer-Encoding"):
            raise RecipeRequestError("配方接口不接受 Transfer-Encoding")
        origins = self.headers.get_all("Origin", [])
        if origins:
            origin = urlparse(origins[0])
            if (len(origins) != 1 or origin.scheme not in ("http", "https")
                    or origin.netloc.lower() != self.headers.get("Host", "").lower()
                    or origin.path or origin.query or origin.fragment):
                raise RecipeRequestError("请在当前咖啡系统页面保存配方", HTTPStatus.FORBIDDEN)
        if (len(self.headers.get_all("Content-Type", [])) != 1
                or self.headers.get_content_type() != "application/json"
                or self.headers.get_content_charset("utf-8") not in ("utf-8", "utf8")):
            raise RecipeRequestError("配方请求必须是 UTF-8 application/json", HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        lengths = self.headers.get_all("Content-Length", [])
        if not lengths:
            raise RecipeRequestError("配方请求必须提供 Content-Length", HTTPStatus.LENGTH_REQUIRED)
        if len(lengths) != 1 or not re.fullmatch(r"[0-9]+", lengths[0]):
            raise RecipeRequestError("Content-Length 不合法")
        # Avoid parsing an unbounded integer header; a decimal length above six
        # significant digits is already larger than the allowed document.
        significant = lengths[0].lstrip("0") or "0"
        if len(significant) > 6 or int(significant) > MAX_RECIPE_BYTES:
            raise RecipeRequestError("配方文件不能超过64KiB", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        length = int(significant)
        if length == 0:
            raise RecipeRequestError("配方内容不能为空")
        try:
            self.connection.settimeout(5)
            body = self.rfile.read(length)
        except OSError as exc:
            raise RecipeRequestError("配方请求未完整接收，请保留输入后重试") from exc
        if len(body) != length:
            raise RecipeRequestError("配方请求长度与实际内容不符")
        return body

    def _xb_recipe_post(self, path):
        self.close_connection = True
        try:
            raw = self._read_xb_recipe_body()
            if path == "/api/xb-recipes/validate":
                self._send_json(preview_recipe(raw))
            elif path.startswith("/api/xb-recipes/"):
                name = unquote(path[len("/api/xb-recipes/"):])
                self._send_json({"item": self.recipe_store.create(name, raw)}, status=HTTPStatus.CREATED)
            else:
                self._send_json({"error": "保存配方需要名称"}, status=HTTPStatus.BAD_REQUEST)
        except RecipeRequestError as exc:
            self._send_json({"error": str(exc)}, status=exc.status)
        except FileExistsError:
            self._send_json({"error": "同名配方已存在；请使用新版本名称，或刷新核对上次保存结果"}, status=HTTPStatus.CONFLICT)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except OSError:
            self._send_json({"error": "配方写入未能确认，请刷新列表核对是否已保存；不要直接重复创建"},
                            status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _read_json(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length).decode("utf-8")
        return json.loads(body or "{}")

    def _extract_item_id(self, path, suffix):
        base = path[len("/api/inventory/") :]
        if suffix:
            base = base[: -len(suffix)]
        base = base.strip("/")
        try:
            return int(base)
        except ValueError as exc:
            raise ValueError("记录 ID 不合法") from exc

    def _extract_green_item_id(self, path, suffix):
        base = path[len("/api/green-inventory/") :]
        if suffix:
            base = base[: -len(suffix)]
        base = base.strip("/")
        try:
            return int(base)
        except ValueError as exc:
            raise ValueError("生豆记录 ID 不合法") from exc

    def _extract_roast_id(self, path, suffix):
        base = path[len("/api/roasts/") :]
        if suffix:
            base = base[: -len(suffix)]
        base = base.strip("/")
        try:
            return int(base)
        except ValueError as exc:
            raise ValueError("烘焙记录 ID 不合法") from exc

    def _extract_bean_batch_id(self, path, suffix):
        base = path[len("/api/bean-batches/") :]
        if suffix:
            base = base[: -len(suffix)]
        base = base.strip("/")
        try:
            return int(base)
        except ValueError as exc:
            raise ValueError("生豆批次 ID 不合法") from exc

    def _extract_record_id(self, path):
        base = path[len("/api/brews/") :].strip("/")
        try:
            return int(base)
        except ValueError as exc:
            raise ValueError("冲煮记录 ID 不合法") from exc

    def _send_html(self, html):
        body = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, path):
        relative_path = unquote(path.removeprefix("/static/"))
        file_path = (STATIC_DIR / relative_path).resolve()
        try:
            file_path.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self._send_json({"error": "Not Found"}, status=HTTPStatus.NOT_FOUND)
            return
        if not file_path.is_file():
            self._send_json({"error": "Not Found"}, status=HTTPStatus.NOT_FOUND)
            return

        body = file_path.read_bytes()
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        if file_path.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        elif file_path.suffix == ".css":
            content_type = "text/css; charset=utf-8"

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    init_db()
    server = None
    selected_port = PORT
    for candidate_port in range(PORT, PORT + 20):
        try:
            server = ThreadingHTTPServer((HOST, candidate_port), CoffeeInventoryHandler)
            selected_port = candidate_port
            break
        except OSError:
            continue
    if server is None:
        raise OSError(f"无法在 {PORT}-{PORT + 19} 中找到可用端口")
    print(f"Coffee inventory server running at http://{HOST}:{selected_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
