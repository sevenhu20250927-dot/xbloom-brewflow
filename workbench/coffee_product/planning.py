"""Pure, reviewable recipe suggestions; no model, storage or device actions.

``base`` is a saved recipe record with bean_id/mode/payload, never a name match.
The three modes return the same strict machine-shaped *reference* payload.
Only mode=xbloom has execution_supported=True; the server must enforce that
boundary again. Validation encodes frames in memory and never sends them.
"""

from __future__ import annotations

import copy
import math
import re
from pathlib import Path

from xbloom_bridge.protocol import build_recipe_frames


REPO = Path(__file__).resolve().parents[2]
PUBLIC_REFERENCE = REPO / "knowledge/source-snapshot/brew-data-package/reference"
PRIVATE_REFERENCE = Path(__file__).resolve().parent / "knowledge/yiyi-v1.9.4/references"
SOURCE_FILES = {
    "yiyi-experience-library": PUBLIC_REFERENCE / "冲煮经验库.md",
    "yiyi-brew-ledger": PUBLIC_REFERENCE / "咖啡冲煮总账.md",
    "yiyi-release-workflow": REPO / "references/yiyi/workflow.md",
    "yiyi-release-framework": REPO / "references/yiyi/knowledge-loop.md",
    "product-planning": REPO / "workbench/README.md",
    "saved-recipe": REPO / "workbench/README.md",
    "local-experience": REPO / "workbench/README.md",
}
METHOD_SOURCES = ("yiyi-release-workflow", "yiyi-release-framework")
if (PRIVATE_REFERENCE / "AGENT.md").is_file() and (PRIVATE_REFERENCE / "萃取框架.md").is_file():
    SOURCE_FILES.update({
        "yiyi-v194-agent": PRIVATE_REFERENCE / "AGENT.md",
        "yiyi-v194-framework": PRIVATE_REFERENCE / "萃取框架.md",
    })
    METHOD_SOURCES = ("yiyi-v194-agent", "yiyi-v194-framework")

SOURCES = {source_id: {"title": path.stem, "path": path}
           for source_id, path in SOURCE_FILES.items()}
SOURCES["product-planning"]["title"] = "工作台配方约束"
SOURCES["saved-recipe"]["title"] = "已保存配方的引用规则"
SOURCES["local-experience"]["title"] = "同批经验的引用与反例规则"
MODES = ("xbloom", "manual", "grind_own")
GOALS = ("", "保持", "保持当前", "保持当前参数", "更甜", "更干净", "减少苦", "更浓", "更清爽", "1:16")


def read_source(source_id: str) -> str:
    """Read an allowlisted source; unknown IDs and arbitrary paths are rejected."""
    if source_id not in SOURCE_FILES:
        raise ValueError("未知资料来源 ID")
    return SOURCE_FILES[source_id].read_text(encoding="utf-8")


def _evidence(source: str, title: str, excerpt: str) -> dict:
    return {"source": source, "title": title, "excerpt": excerpt}


def _ag(value) -> float | None:
    # A missing or descriptive roast level stays nonnumeric; never infer AG
    # from price, estate name, origin, elevation or flavor descriptions.
    if type(value) in (int, float):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        match = re.fullmatch(r"(?:AG\s*)?(\d+(?:\.\d+)?)", value.strip(), re.I)
        if match:
            ag = float(match.group(1))
            return ag if math.isfinite(ag) else None
    return None


def check_dose(grams):
    if type(grams) is not int or not 5 <= grams <= 18:
        raise ValueError("粉量须为 5–18 g 的整数")
    return grams


def _initial(bean: dict, goal: str, dose: int, rationale: list, risks: list) -> dict:
    process = str(bean.get("process") or "").lower()
    ag = _ag(bean.get("roast_level"))
    washed = "水洗" in process or "washed" in process
    natural = not washed and ("日晒" in process or "natural" in process)
    honey = not washed and not natural and ("蜜" in process or "honey" in process)
    grind = 50 if washed else 52 if natural else 51 if honey else 52
    pauses = [12, 12, 10, 0] if natural else [12, 16, 12, 0]
    temps = [93, 92, 92, 90]
    label = "水洗" if washed else "日晒" if natural else "蜜处理" if honey else "未知处理法"
    if ag is None:
        risks.append("烘焙度数值未知；未推定 AG，当前是待校准的通用四段草案。")
    elif ag < 75:
        # A local adaptation of the source's lower-temperature direction, not
        # a copy of its 55–70 grinder range or a claim of validated equivalence.
        grind, temps = 55, [90, 88, 87, 85]
        rationale.append(f"条件：已提供 AG {ag:g}；参考原文中烘以上降温方向，拟用 90/88/87/85℃、55 档。")
        risks.append("中深烘温度为本地四段适配假设；原文更粗的中烘研磨域未移植，首杯必须人工审阅。")
    elif ag >= 90:
        risks.append(f"已提供 AG {ag:g}；原文对极浅豆另有五段/高温分流，首版未自动启用，四段可能萃取不足。")
    rationale.append(f"条件：{label}；结合已知烘焙信息给 {grind} 档四段起点，不按豆名或庄园名复制历史锚点。")
    if honey:
        risks.append("蜜处理未按风味描述自动定端；当前研磨及水洗驻留只作待审核起点。")
    if any(word in process for word in ("厌氧", "发酵", "酵母", "浸渍", "anaerobic", "ferment", "yeast", "carbonic")):
        risks.append("处理法含发酵提示；首版未移植专用骨架，当前四段不能视为已经适配。")
    if not bean.get("roast_date"):
        risks.append("烘焙日期未知；未假定豆龄，也未自动套用新鲜豆开关。")
    else:
        risks.append(f"已保留烘焙日期 {bean['roast_date']}；养豆与储存状态仍须人工核对，未自动按日历天数调参。")
    ratio = 16 if goal == "1:16" else 15
    water = dose * ratio
    main, remainder = divmod(water - 3 * dose, 3)
    volumes = [3 * dose, main, main, main + remainder]
    rationale.append(f"规则草案按 {dose} g、1:{ratio} 分配 {water} ml 过粉水，转速 60 RPM。")
    if dose != 15:
        risks.append(f"{dose} g 沿用通用四段起点，尚待本杯验证。")
    rationale.append(f"温度路线 {'/'.join(map(str, temps))}℃；水洗 12/16/12s、日晒 12/12/10s 驻留参考一一原文，当前段量及 60 RPM 是本地适配，尚无本机效果证明。")
    rationale.append("闷蒸用 3.0ml/s 作为低扰动润湿起点，主段 3.5ml/s；末段驻留 0s，振动关闭，均须观察实际粉床与尾滴。")
    return {
        "cupType": "xdripper", "doseGrams": dose,
        "recipe": {
            "grinderSize": grind, "rpm": 60, "grandWater": water,
            "pours": [
                {"volume": volume, "temperature": temp,
                 "flowRate": 3.0 if index == 0 else 3.5,
                 "pattern": 1 if index == 3 else 2, "pausing": pause,
                 "vibBefore": False, "vibAfter": False}
                for index, (volume, temp, pause) in enumerate(zip(volumes, temps, pauses))
            ],
        },
    }


def _adjust(payload: dict, goal: str, rationale: list, risks: list) -> None:
    r = payload["recipe"]
    if not goal or goal in ("保持", "保持当前", "保持当前参数"):
        rationale.append("动作：保持参考配方原值；保持或重复不等于已验证满意。")
    elif goal in ("更甜", "更干净"):
        before = r["grinderSize"]
        r["grinderSize"] += -1 if goal == "更甜" else 1
        expected = "尝试提高甜感" if goal == "更甜" else "尝试减轻浑杂、提高干净度"
        rationale.append(f"动作：只改研磨 {before}→{r['grinderSize']} 档；预期：{expected}，其余参数保持。")
        risks.append("反例判据：变细后苦涩/堵塞或变粗后空薄，即不支持本次假设；无品饮反馈保持未知。")
    elif goal == "减少苦":
        before = [p["temperature"] for p in r["pours"]]
        for pour in r["pours"]:
            pour["temperature"] -= 1
        after = [p["temperature"] for p in r["pours"]]
        rationale.append(f"动作：只将温度路线整体降 1℃（{before}→{after}）；预期减轻苦感，尚不能判定原因为过萃。")
        risks.append("先核对实际粉量、杯内液重及三温段反馈；降温可能损失甜感，苦味未退即不支持本次假设。")
    elif goal in ("更浓", "更清爽", "1:16"):
        before = r["grandWater"]
        target = (before - payload["doseGrams"] if goal == "更浓" else
                  before + payload["doseGrams"] if goal == "更清爽" else payload["doseGrams"] * 16)
        if target / payload["doseGrams"] < 14:
            raise ValueError("更浓会低于建议的 1:14 下限；请人工审核，不自动夹断")
        r["pours"][-1]["volume"] += target - before
        r["grandWater"] = target
        expected = "提高浓度" if goal == "更浓" else "减轻浓度、保持研磨不变" if goal == "更清爽" else "达到明确要求的 1:16"
        rationale.append(f"动作：过粉水量 {before}→{target}ml，差额只改末段水量；粉量与其余参数保持。预期{expected}，不能据此宣称萃取率提高。")
        risks.append("末段水量改变会同时改变水头与萃取时间；苦感或空薄加重即为反例，不能只比较尾滴秒数。")


def _experience_evidence(bean: dict, experiences: list, evidence: list, risks: list) -> None:
    for item in experiences:
        if item.get("bean_id") != bean["id"]:
            continue
        evaluations = item.get("evaluations") or []
        counter = [str(e.get("notes") or "未附说明") for e in evaluations
                   if e.get("verdict") == "counterexample"]
        supports = sum(e.get("verdict") == "support" for e in evaluations)
        evidence.append(_evidence(
            "local-experience", f"同批经验候选 #{item.get('id', '未编号')}",
            f"条件：{item.get('condition') or '未记录'}；动作：{item.get('action') or '未记录'}；"
            f"预期：{item.get('expected') or '未记录'}；引用：brew_id={item.get('source_brew_id')}、"
            f"person_id={item.get('source_person_id')}；反例：{'；'.join(counter) if counter else '未记录，不代表不存在'}；"
            f"支持记录 {supports} 条，只表示观察一致、不证明因果。备注：{item.get('notes') or '无'}"))
    if experiences:
        rationale_note = "经验仅作人工审核依据，本次参数只依据明确目标调整；不同人的口味不自动合并。"
        risks.append(rationale_note)


def suggest(bean: dict, *, mode: str = "xbloom", goal: str = "", base: dict | None = None,
            experiences: list[dict] | None = None, dose_grams: int | None = None) -> dict:
    """Return a suggestion without reading a DB, writing files or starting a cup.

    Raises ValueError/ProtocolError on unsupported goals, cross-bean bases,
    mapping-bound conflicts or unencodable payloads. No clamping or repair.
    """
    if not isinstance(bean, dict) or type(bean.get("id")) is not int:
        raise ValueError("bean 必须含主库整数 id")
    if mode not in MODES:
        raise ValueError("mode 必须为 xbloom/manual/grind_own")
    if not isinstance(goal, str) or goal.strip() not in GOALS:
        raise ValueError("首版目标支持：更甜、更干净、减少苦、更浓、更清爽、保持、1:16；其他目标请人工修改参数")
    goal = goal.strip()
    rationale, risks = [], []
    evidence = [
        _evidence("product-planning", "本轮本地约束与迁移边界", "新杯默认 15 g，可选择粉量；默认 1:15、60 RPM；48–55 为建议映射范围。"),
        _evidence(METHOD_SOURCES[1], "一一的萃取框架", "参考温度、驻留、参数方向与反例判读；原文的实测属于作者环境，不是本机验证。"),
        _evidence(METHOD_SOURCES[0], "检索与反馈纪律", "同杯目标保持可比、引用上杯、一次只换一个可辨认杠杆；两杯一致不能证明因果。"),
    ]
    if base is not None:
        if base.get("bean_id") != bean["id"]:
            raise ValueError("base 必须属于同一 bean_id，不按名称匹配")
        if base.get("mode") != mode:
            raise ValueError("base 的制作模式不同；请人工审核迁移后另存配方")
        payload = copy.deepcopy(base.get("payload"))
        build_recipe_frames(payload)
        if dose_grams is not None and check_dose(dose_grams) != payload["doseGrams"]:
            raise ValueError("所选粉量与参考配方不同，可按新粉量拟规则草案，或在原配方中选择新粉量并提交 AI 修方。")
        rationale.append(f"引用同批已保存配方 #{base.get('id', '未编号')}；它优先于外部庄园锚点，保存本身不证明实冲效果。")
        evidence.insert(0, _evidence("saved-recipe", f"已保存配方 #{base.get('id', '未编号')}",
                                   f"bean_id={bean['id']}；仅按本次目标 {goal or '保持'} 调整，保留其他原值。"))
        _adjust(payload, goal, rationale, risks)
    else:
        payload = _initial(bean, goal, check_dose(15 if dose_grams is None else dose_grams), rationale, risks)
        if goal != "1:16":
            _adjust(payload, goal, rationale, risks)
    if payload["recipe"]["rpm"] != 60:
        raise ValueError("当前用户要求 60 RPM；参考配方冲突，请人工审核，不自动替换")
    if not 48 <= payload["recipe"]["grinderSize"] <= 55:
        raise ValueError("建议研磨超出 48–55 映射范围，请人工审核，不自动夹断")
    build_recipe_frames(payload)
    _experience_evidence(bean, experiences or [], evidence, risks)
    if mode == "grind_own":
        risks.append("机器免磨动作尚未接通；payload 中研磨档仅为 xBloom 参照，不能当作免磨执行代码或直接换算外部磨豆机。")
    elif mode == "manual":
        risks.append("全手冲仅提供参考参数，须按实际滤杯与磨豆机人工修改；xBloom 档位不是手摇磨豆机刻度。")
    risks.append("建议与协议可编码不等于风味有效；只有当杯明确授权才能启动真实机器。")
    suffix = goal or ("首杯参考" if base is None else "沿用参考")
    return {
        "title": f"{bean.get('name') or '未命名豆'} · {suffix}",
        "mode": mode, "goal": goal, "payload": payload,
        "rationale": rationale, "evidence": evidence, "risks": list(dict.fromkeys(risks)),
        "provenance": "本地确定性规则；一一的拟方方法为外部建议来源；未运行模型或实机验证",
        "execution_supported": mode == "xbloom",
    }
