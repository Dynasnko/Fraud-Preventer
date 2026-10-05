import json
import os
from typing import List, Set

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_workers.json")

_state: dict = {"user_created": [], "disabled": []}


def _load() -> None:
    global _state
    if os.path.exists(_CONFIG_PATH):
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                _state = json.load(f)
        except Exception:
            pass


def _save() -> None:
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(_state, f, ensure_ascii=False, indent=2)


_load()


def get_user_created_workers() -> List[str]:
    return list(_state.get("user_created", []))


def add_user_created_worker(name: str) -> None:
    if name not in _state.setdefault("user_created", []):
        _state["user_created"].append(name)
        _save()


def get_disabled_workers() -> Set[str]:
    return set(_state.get("disabled", []))


def set_worker_disabled(worker_id: str, disabled: bool) -> None:
    disabled_set = set(_state.get("disabled", []))
    if disabled:
        disabled_set.add(worker_id)
    else:
        disabled_set.discard(worker_id)
    _state["disabled"] = list(disabled_set)
    _save()


def rename_user_created_worker(old_name: str, new_name: str) -> None:
    lst = _state.setdefault("user_created", [])
    if old_name in lst:
        lst[lst.index(old_name)] = new_name
    old_wid = f"worker_{old_name}"
    new_wid = f"worker_{new_name}"
    disabled_set = set(_state.get("disabled", []))
    if old_wid in disabled_set:
        disabled_set.discard(old_wid)
        disabled_set.add(new_wid)
    _state["disabled"] = list(disabled_set)
    _save()


def remove_user_created_worker(name: str) -> None:
    lst = _state.setdefault("user_created", [])
    if name in lst:
        lst.remove(name)
    wid = f"worker_{name}"
    disabled_set = set(_state.get("disabled", []))
    disabled_set.discard(wid)
    _state["disabled"] = list(disabled_set)
    _save()
