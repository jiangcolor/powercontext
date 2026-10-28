"""Deterministic game rules; narration belongs to Dify's LLM node."""
from __future__ import annotations

BRANCHES = {
    "自由": ("自由放养", "它成了流浪时间的导游，带着三个迷路的星期一回来了。", "放手收藏家"),
    "打工": ("营业上岗", "它开了一家只在周一营业的店，今天寄来第一张工资单：两小时午睡。", "时间资本家"),
    "朋友": ("成为朋友", "它为你留了一把椅子；所有人都催你快一点，只有它说：慢慢来。", "异物知己"),
}


class RuleError(ValueError):
    pass


def advance(state: dict | None, action: str, offering: str) -> tuple[dict, str]:
    """Return the next structured state and trusted facts the narrator must preserve."""
    if action == "寄存":
        if state:
            raise RuleError("这件物品已经寄存，请先改写或重逢；想开新故事请换一张玩家卡。")
        if not offering.strip() or len(offering) > 120:
            raise RuleError("请用 1—120 个字描述一件离谱物品。")
        state = {"item": offering.strip(), "chapter": 1, "choice": None, "ending": None}
        return state, "第一幕：登记成功。给物品一个小怪癖，提供三个去向：自由、打工、朋友。请玩家下次选改写。"
    if not state:
        raise RuleError("柜子还是空的。请先选择寄存，描述一件离谱物品。")
    state = dict(state)
    if action == "改写":
        if state["chapter"] != 1:
            raise RuleError("命运已经签收，请选择重逢查看后果。")
        choices = [key for key in BRANCHES if key in offering]
        if len(choices) != 1:
            raise RuleError("请在输入中只选择一种去向：自由、打工、朋友。可以补充你的理由。")
        state.update(chapter=2, choice=choices[0], reason=offering.strip()[:200])
        return state, f"第二幕：玩家决定{BRANCHES[choices[0]][0]}。让物品作出有趣反应，留下一个悬念，提示下次选择重逢。"
    if action == "重逢":
        if state["chapter"] == 1:
            raise RuleError("它还没选好去向。请先选择改写：自由、打工、朋友。")
        state.update(chapter=3, ending=BRANCHES[state["choice"]][2])
        return state, f"第三幕：{BRANCHES[state['choice']][1]} 必须呼应玩家当初的选择与物品。结局称号：{state['ending']}。再次重逢可以写不同的日常后记，但不能改变结局。"
    raise RuleError("请选择寄存、改写或重逢。")
