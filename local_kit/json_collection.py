"""
json_collection.py — 通用 GitHub-backed JSON CRUD 引擎。
不強行統一schema欄位，只統一「單檔JSON存於固定前綴目錄」這個結構模式。
"""
import json
from datetime import datetime


class Collection:
    def __init__(self, gh_prefix, id_field, default_fields, gh_get, gh_put, gh_delete, gh_list):
        """
        gh_prefix: 如 "data/brands/"
        id_field: 該schema用哪個欄位當檔名，如 "brand_id"
        default_fields: 建立時套用的預設值
        gh_get/gh_put/gh_delete/gh_list: 呼叫端傳入既有的GitHub Contents API函式
        """
        self.gh_prefix = gh_prefix
        self.id_field = id_field
        self.default_fields = default_fields
        self._gh_get = gh_get
        self._gh_put = gh_put
        self._gh_delete = gh_delete
        self._gh_list = gh_list

    def list(self, env):
        files = self._gh_list(env, self.gh_prefix)  # 502由呼叫端的RuntimeError轉譯
        return sorted(f[:-5] for f in files if f.endswith(".json"))

    def get(self, env, item_id):
        content, _ = self._gh_get(env, self.gh_prefix + "%s.json" % item_id)
        try:
            return json.loads(content)
        except ValueError:
            raise ValueError("資料格式錯誤：%s 內容非合法JSON，需人工檢查該檔內容" % item_id)

    def create(self, env, item_id, data, extra_fields=None):
        gh_path = self.gh_prefix + "%s.json" % item_id
        try:
            self._gh_get(env, gh_path)
            raise FileExistsError("%s 已存在，若要修改請使用更新流程（本階段未提供），或更換 item_id" % item_id)
        except FileNotFoundError:
            pass
        obj = dict(self.default_fields)
        obj.update(data)
        if extra_fields:
            obj.update(extra_fields)
        obj.setdefault("version", 1)
        obj.setdefault("last_updated", datetime.now().strftime("%Y-%m-%d"))
        content = json.dumps(obj, ensure_ascii=False, indent=2)
        self._gh_put(env, gh_path, content, "%s: add %s [auto-backup]" % (self.gh_prefix.strip("/"), item_id))
        return obj

    def delete(self, env, item_id):
        """
        不經過safe_git。日常單筆刪除，已有UI按住3秒防呆＋GitHub sha樂觀鎖。
        """
        gh_path = self.gh_prefix + "%s.json" % item_id
        _, sha = self._gh_get(env, gh_path)  # 不存在則呼叫端轉404
        self._gh_delete(env, gh_path, "%s: delete %s [auto-backup]" % (self.gh_prefix.strip("/"), item_id), sha)
        return True
