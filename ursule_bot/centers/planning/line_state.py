from __future__ import annotations

from .regrind import BRITISH_LIGHT_CRUISER_LINE


def update_line_state(previous_port: list[int] | None, current_port: list[int] | None, completed_cycles: int, current_ship_index: int, waiting_for_reset: bool) -> dict:
    state = {
        "completed_cycles": max(0, completed_cycles),
        "current_ship_index": min(max(0, current_ship_index), 4),
        "waiting_for_reset": bool(waiting_for_reset),
        "event": "",
    }
    if current_port is None:
        return state
    current = set(map(int, current_port))
    previous = set(map(int, previous_port)) if previous_port is not None else None
    ids = [int(ship["ship_id"]) for ship in BRITISH_LIGHT_CRUISER_LINE]
    if previous is None:
        owned = [index for index, ship_id in enumerate(ids) if ship_id in current]
        if owned and not state["waiting_for_reset"]:
            state["current_ship_index"] = max(owned)
        return state
    if state["waiting_for_reset"] and ids[-1] in previous and ids[-1] not in current:
        state.update({
            "waiting_for_reset": False,
            "current_ship_index": max((i for i, ship_id in enumerate(ids[:-1]) if ship_id in current), default=0),
            "event": "检测到米诺陶离港，本轮重置开始",
        })
        return state
    if not state["waiting_for_reset"]:
        if ids[3] in previous and ids[3] not in current and ids[0] in current:
            state.update({
                "completed_cycles": state["completed_cycles"] + 1,
                "current_ship_index": 0,
                "event": "检测到涅普顿离港且利安得入港：上一轮完成，下一轮开始",
            })
            return state
        higher = [i for i, ship_id in enumerate(ids) if ship_id in current and i > state["current_ship_index"]]
        if higher:
            old_name = BRITISH_LIGHT_CRUISER_LINE[state["current_ship_index"]]["name"]
            state["current_ship_index"] = max(higher)
            state["event"] = f"检测到{old_name}之后的高级舰船入港"
    return state
