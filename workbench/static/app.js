const { createApp } = Vue;

const beanFields = [
  ["name", "名称", "text", true],
  ["roaster", "烘焙商", "text", true],
  ["roaster_recommendation", "烘焙商推荐参数"],
  ["country", "国家", "text", true],
  ["region", "产区"],
  ["producer", "庄园/生产者", "text", true],
  ["lot_info", "地块/批次"],
  ["variety_name", "豆种名称"],
  ["roast_date", "烘焙日期", "date", true],
  ["storage_state", "保存状态", "select", true, ["常温", "冷冻"]],
  ["process", "处理法", "text", true],
  ["total_weight", "总克数（g）", "number"],
  ["net_weight", "剩余克数（g）", "number", true],
  ["price_total", "剩余金额（元）", "number", true],
];

const greenBeanFields = [
  ["crop_season", "产季"],
  ["region", "产区"],
  ["bean_type", "豆种"],
  ["estate", "庄园"],
  ["plot", "地块"],
  ["batch", "批次"],
  ["flavor_notes", "风味描述", "textarea"],
  ["supplier", "生豆商"],
  ["process", "处理法"],
  ["moisture_pct", "含水率（%）", "number"],
  ["density", "密度", "number"],
  ["total_weight", "总量（g）", "number", true],
];

const roastLevelOptions = [
  ["very_light", "极浅"],
  ["light", "浅烘"],
  ["light_medium", "浅中烘"],
  ["medium", "中烘"],
  ["dark", "深烘"],
  ["unknown", "未判断"],
];

const changedVariableOptions = [
  ["", "未指定"],
  ["load", "载量"],
  ["heat", "火力"],
  ["fan", "风门"],
  ["development", "发展时间"],
  ["bean", "豆子"],
  ["profile", "曲线/方案"],
  ["other", "其他"],
];

const roastEventTypeOptions = [
  ["charge", "入豆"],
  ["turning_point", "回温点"],
  ["yellow", "黄点"],
  ["first_crack_start", "一爆开始"],
  ["first_crack_end", "一爆结束"],
  ["drop", "下豆"],
  ["heat_change", "火力调整"],
  ["fan_change", "风门调整"],
  ["note", "备注"],
];

const cuppingScoreFields = [
  ["dry_aroma", "干香"],
  ["wet_aroma", "湿香"],
  ["acidity", "酸质"],
  ["sweetness", "甜感"],
  ["bitterness", "苦感"],
  ["body", "醇厚"],
  ["clarity", "干净度"],
  ["aftertaste", "余韵"],
  ["balance", "平衡"],
  ["overall", "总评"],
];

const brewSections = [
  {
    key: "technique",
    title: "冲煮手法",
    fields: [
      ["grind_size", "研磨度 / 刻度"],
      ["roaster_recommended_grind", "烘焙商推荐研磨度"],
      ["dose", "粉量"],
      ["yield", "出液"],
      ["ratio", "比例"],
      ["water_temperature", "水温"],
      ["bloom", "闷蒸"],
      ["pour_method", "注水方式"],
      ["total_time", "总时间"],
      ["water_type", "水类型"],
      ["water_tds", "TDS"],
      ["water_mg_ca", "镁/钙比例"],
      ["grinder", "磨豆机 / 刀盘"],
      ["dripper", "滤杯"],
      ["filter_paper", "滤纸"],
      ["kettle", "水壶"],
      ["flow_judgement", "流速判断", "checks", ["偏慢", "正常", "偏快"]],
      ["coffee_bed", "粉床", "checks", ["平整", "中央塌陷", "挂壁严重", "局部凹陷"]],
      ["extraction_observation", "萃取观察", "checks", ["流速稳定", "咖啡床平整", "有细粉聚集", "有堵塞趋势", "粉床不平"]],
      ["extraction_notes", "萃取备注", "textarea"],
      ["grind_notes", "研磨补充说明", "textarea"],
    ],
  },
  {
    key: "tasting",
    title: "风味品评",
    fields: [
      ["acidity_style", "酸质"],
      ["sweetness_style", "甜感"],
      ["clarity_style", "层次"],
      ["finish_style", "尾段"],
      ["score", "总体满意度（0-10）", "number"],
      ["flavor_direction", "风味方向", "checks", ["柑橘", "浆果", "花香", "甘蔗糖", "蜂蜜", "巧克力", "茶感", "谷物"]],
      ["flavor_description", "具体描述", "textarea"],
      ["structure_acidity", "酸质（0-5）", "number"],
      ["structure_sweetness", "甜感（0-5）", "number"],
      ["structure_body", "醇厚（0-5）", "number"],
      ["structure_cleanliness", "干净度（0-5）", "number"],
      ["structure_clarity", "层次感/解析力（0-5）", "number"],
      ["structure_balance", "平衡度（0-5）", "number"],
      ["aftertaste_length", "余韵时长"],
      ["aftertaste_type", "余韵类型"],
      ["retronasal", "鼻后嗅"],
      ["defects", "缺点", "textarea"],
    ],
  },
  {
    key: "improvement",
    title: "后续改进建议",
    fields: [["next_adjustment", "下次调整建议（只改1个变量）", "textarea"]],
  },
];

function fieldName(field) {
  return field[0];
}

function fieldLabel(field) {
  return field[1];
}

function fieldType(field) {
  return field[2] || "text";
}

function fieldRequired(field) {
  return Boolean(field[3] === true);
}

function fieldOptions(field) {
  return Array.isArray(field[3]) ? field[3] : field[4] || [];
}

function hasExportValue(value) {
  if (Array.isArray(value)) return value.length > 0;
  return value !== undefined && value !== null && String(value).trim() !== "";
}

function formatExportValue(value) {
  if (Array.isArray(value)) return value.join("、");
  return String(value ?? "").trim();
}

function markdownValue(value) {
  return formatExportValue(value).replace(/\n/g, " / ");
}

function blankBean() {
  return {
    name: "",
    roaster: "",
    roaster_recommendation: "",
    country: "",
    region: "",
    producer: "",
    lot_info: "",
    variety_name: "",
    roast_date: "",
    storage_state: "常温",
    process: "",
    total_weight: "",
    net_weight: "",
    price_total: "",
  };
}

function blankGreenBean() {
  return {
    name: "",
    origin: "",
    crop_season: "",
    region: "",
    bean_type: "",
    estate: "",
    variety_name: "",
    plot: "",
    batch: "",
    flavor_notes: "",
    supplier: "",
    process: "",
    moisture_pct: "",
    density: "",
    purchase_weight_g: "",
    remaining_green_weight_g: "",
    notes: "",
    total_weight: "",
  };
}

function blankBeanBatch() {
  return {
    name: "",
    origin: "",
    process: "",
    variety: "",
    purchase_weight_g: "",
    remaining_green_weight_g: "",
    notes: "",
  };
}

function blankRoastEvent() {
  return {
    event_type: "note",
    time_sec: "",
    temp_c: "",
    heat_setting: "",
    fan_setting: "",
    note: "",
  };
}

function blankRoast() {
  return {
    roast_date: new Date().toISOString().slice(0, 10),
    bean_id: "",
    bean_batch_id: "",
    bean_name_snapshot: "",
    bean_origin: "",
    bean_process: "",
    bean_variety: "",
    roaster_model: "Santoker Cube10",
    roast_label: "",
    batch_weight_g: "",
    roasted_weight_g: "",
    cupping_reserved_g: 8.25,
    create_roasted_batch: false,
    profile_name: "",
    charge_temp_c: "",
    preheat_temp_c: "",
    ambient_temp_c: "",
    fan_start: "",
    heat_start: "",
    operation_plan: "",
    plan_yellow_time_s: "",
    plan_yellow_temp_c: "",
    plan_first_crack_time_s: "",
    plan_first_crack_temp_c: "",
    plan_drop_time_s: "",
    plan_drop_temp_c: "",
    plan_note: "",
    yellow_time_sec: "",
    yellow_temp_c: "",
    first_crack_time_sec: "",
    first_crack_temp_c: "",
    drop_time_sec: "",
    drop_temp_c: "",
    actual_yellow_time_s: "",
    actual_yellow_temp_c: "",
    actual_first_crack_time_s: "",
    actual_first_crack_temp_c: "",
    actual_drop_time_s: "",
    actual_drop_temp_c: "",
    control_log: "",
    roast_notes: "",
    experiment_goal: "",
    changed_variable: "",
    hypothesis: "",
    result_summary: "",
    next_adjustment: "",
    roast_level: "unknown",
    color_note: "",
    aroma_note: "",
    defect_flags: "",
    general_notes: "",
    learning_note: "",
    cupping_date: "",
    cupping_score: "",
    cupping_notes: "",
    defects: "",
    events: [blankRoastEvent()],
  };
}

function blankCupping() {
  return {
    cupping_date: new Date().toISOString().slice(0, 10),
    rest_hours: "",
    dose_g: 8.25,
    water_ml: 150,
    water_temp_c: 93,
    grind_setting: "",
    grinder: "",
    dry_aroma: "",
    wet_aroma: "",
    acidity: "",
    sweetness: "",
    bitterness: "",
    body: "",
    clarity: "",
    aftertaste: "",
    balance: "",
    overall: "",
    flavor_notes: "",
    defect_notes: "",
    conclusion: "",
    next_roast_adjustment: "",
  };
}

function resolveView() {
  const path = location.pathname;
  if (path === "/xb-recipes") return "xb-recipes";
  if (path === "/tastings") return "tastings";
  if (path === "/brews") return "brews";
  if (path === "/green") return "green";
  if (/^\/beans\/\d+\/roasts\/new$/.test(path)) return "bean-roast-new";
  if (/^\/beans\/\d+$/.test(path)) return "bean-batch-detail";
  if (path === "/roasts/new") return "roast-new";
  if (path === "/roasts/compare") return "roast-compare";
  if (/^\/roasts\/\d+\/cupping$/.test(path)) return "roast-cupping";
  if (/^\/roasts\/\d+\/edit$/.test(path)) return "roast-edit";
  if (/^\/roasts\/\d+$/.test(path)) return "roast-detail";
  if (path === "/roasts") return "roasts";
  return "inventory";
}

function routeRoastId() {
  const match = location.pathname.match(/^\/roasts\/(\d+)/);
  return match ? Number(match[1]) : null;
}

function routeBeanBatchId() {
  const match = location.pathname.match(/^\/beans\/(\d+)/);
  return match ? Number(match[1]) : null;
}

function blankBrewData() {
  const data = {
    bean_context: { roast_degree: "", warming_time: "" },
    technique: {},
    tasting: {},
    improvement: {},
  };
  for (const section of brewSections) {
    for (const field of section.fields) {
      data[section.key][fieldName(field)] = fieldType(field) === "checks" ? [] : "";
    }
  }
  return data;
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function blankXbPour() {
  return { volume: "", temperature: "", flowRate: 3.0, pattern: 2,
    pausing: 0, vibBefore: false, vibAfter: false };
}

function blankXbRecipe() {
  return { cupType: "xdripper", doseGrams: "", recipe: {
    grinderSize: "", rpm: 90, grandWater: "", pours: [blankXbPour()],
  } };
}

function xbErrorMessage(message) {
  if (typeof message !== "string") return "服务返回了无法识别的错误，请保留输入并刷新后核对。";
  const known = {
    "grandWater must equal sum of pour volumes": "各段注水量之和必须等于总注水量，请核对两处数值。",
    "ratio cannot be encoded exactly; review recipe instead of rounding": "当前粉量和总注水量的组合无法被机器准确执行，请调整粉量或总注水量后重新检查。",
    "firmware ratio arithmetic differs from reviewed water volume": "机器计算这组粉水比时会产生水量偏差，请调整粉量或总注水量；系统不会自动修改参数。",
    "rpm must be in 10 RPM steps": "研磨转速请选择60、70、80、90、100、110或120 RPM。",
    "pours must contain 1..9 entries": "配方需要包含1–9段注水。",
    "only reviewed Omni xdripper cupType is supported": "当前仅支持 Omni 滤杯配方。",
    "recipe exceeds 64 KiB": "配方文件过大，请控制在64KiB以内。",
    "recipe document must be UTF-8 bytes": "配方文件的文字编码不受支持，请使用UTF-8格式。",
    "recipe must be a regular file": "请选择普通配方文件，不能选择文件夹或其他类型。",
    "JSON decimal cannot be represented": "配方中存在无法准确表示的数值，请检查小数位和数值大小。",
    "JSON number loses decimal precision or is nonfinite": "配方中存在精度过高或无效的数值，请使用允许范围内的数值。",
    "encoded recipe too long": "配方内容超出机器支持范围，请减少注水段数后重新检查。",
  };
  if (Object.hasOwn(known, message)) return known[message];
  const fields = {
    doseGrams: "粉量（g）", grinderSize: "研磨档位", rpm: "研磨转速（RPM）",
    grandWater: "总注水量（ml）", volume: "注水量（ml）", temperature: "水温",
    flowRate: "流速", pattern: "注水轨迹", pausing: "注水后停顿（秒）",
    vibBefore: "注水前振动", vibAfter: "注水后振动", cupType: "滤杯类型",
  };
  const pour = message.match(/pours\[(\d+)\]/);
  const prefix = pour ? `第${Number(pour[1]) + 1}段` : "";
  const integer = message.match(/^(.+) must be an integer in (-?\d+)\.\.(-?\d+)$/);
  if (integer) {
    const field = integer[1].split(".").pop();
    if (field === "temperature") return `${prefix}水温请选择40–95℃、常温 RT或BP。`;
    if (field === "pattern") return `${prefix}注水轨迹请选择中心、环绕或螺旋。`;
    if (field === "rpm") return known["rpm must be in 10 RPM steps"];
    if (Object.hasOwn(fields, field)) return `${prefix}${fields[field]}必须填写${integer[2]}–${integer[3]}之间的整数。`;
  }
  const duplicate = message.match(/^duplicate JSON key: ['"]([^'"]+)['"]$/);
  if (duplicate && Object.hasOwn(fields, duplicate[1])) {
    return `配方中的“${fields[duplicate[1]]}”重复出现，请只保留一处。`;
  }
  if (message.endsWith(".temperature must be 40..95 C, RT=20, or BP=98")) {
    return `${prefix}水温请选择40–95℃、常温 RT或BP。`;
  }
  if (message.endsWith(".flowRate must be one of 3.0/3.1/3.2/3.3/3.4/3.5")) {
    return `${prefix}流速请选择3.0–3.5ml/s之间的数值，每次间隔0.1。`;
  }
  if (message.endsWith(": vibration flags must be booleans")) {
    return `${prefix}振动选项必须明确选择开启或关闭。`;
  }
  if (message.startsWith("nonfinite JSON number is not allowed:")) {
    return "配方中存在无效数字，请检查空值或超出范围的数值。";
  }
  // Unknown errors retain the service's message instead of implying a diagnosis.
  return message;
}

async function xbRequest(url, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch(url, {
      ...options, headers: { "Content-Type": "application/json" }, signal: controller.signal,
    });
    let result;
    try {
      result = await response.json();
    } catch (_) {
      throw new Error("服务返回了无法识别的响应，请刷新列表核对。");
    }
    if (!response.ok) {
      const error = new Error(xbErrorMessage(result.error || "请求失败，请保留当前输入后重试。"));
      error.originalMessage = result.error;
      error.status = response.status;
      throw error;
    }
    return result;
  } catch (error) {
    if (error.name === "AbortError") throw new Error("请求超时。");
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "请求失败");
  return data;
}

const FieldInput = {
  props: ["model", "field"],
  methods: { fieldName, fieldLabel, fieldType, fieldRequired, fieldOptions },
  template: `
    <label :class="{ full: fieldType(field) === 'textarea' || fieldType(field) === 'checks' }">
      {{ fieldLabel(field) }}

      <select v-if="fieldType(field) === 'select'" v-model="model[fieldName(field)]" :required="fieldRequired(field)">
        <option v-for="option in fieldOptions(field)" :key="option" :value="option">{{ option }}</option>
      </select>

      <textarea v-else-if="fieldType(field) === 'textarea'" v-model="model[fieldName(field)]"></textarea>

      <div v-else-if="fieldType(field) === 'checks'" class="checks">
        <label v-for="option in fieldOptions(field)" :key="option">
          <input type="checkbox" :value="option" v-model="model[fieldName(field)]">
          {{ option }}
        </label>
      </div>

      <input
        v-else
        v-model="model[fieldName(field)]"
        :type="fieldType(field)"
        :required="fieldRequired(field)"
        :min="fieldType(field) === 'number' ? 0 : undefined"
        :step="fieldType(field) === 'number' ? '0.01' : undefined"
      >
    </label>
  `,
};

const FieldGrid = {
  props: ["fields", "model"],
  components: { FieldInput },
  template: `
    <div class="form-grid">
      <field-input v-for="field in fields" :key="field[0]" :field="field" :model="model"></field-input>
    </div>
  `,
};

const BrewFields = {
  props: ["data"],
  components: { FieldGrid },
  data() {
    return { brewSections };
  },
  template: `
    <div>
      <section v-for="section in brewSections" :key="section.key" class="section">
        <h3>{{ section.title }}</h3>
        <field-grid :fields="section.fields" :model="data[section.key]"></field-grid>
      </section>
    </div>
  `,
};

createApp({
  components: { FieldGrid, FieldInput, BrewFields, TastingRoom },
  data() {
    return {
      view: resolveView(),
      initialBrewAnchor: location.hash,
      routeRoastId: routeRoastId(),
      routeBeanBatchId: routeBeanBatchId(),
      inventoryView: "current",
      beanFields,
      importedBeanFields: beanFields.map(([key, label, kind, required, options]) => [key, label, kind, key === "name", key === "storage_state" ? ["待补", "常温", "冷冻", "已取出冷冻"] : options]),
      greenBeanFields,
      inventory: { items: [], summary: { total_net_weight: 0, total_cups: 0, recommendation: null } },
      greenInventory: { items: [], summary: { total_weight: 0, active_count: 0 } },
      beanBatches: [],
      beanBatchDetail: null,
      roasts: [],
      roastDetail: null,
      brews: [],
      xbRecipes: [],
      xbFileErrors: [],
      xbListError: "",
      xbLoading: false,
      xbDraft: blankXbRecipe(),
      xbName: "",
      xbSourceName: "",
      xbValidation: null,
      xbChecking: false,
      xbSaving: false,
      xbMessage: "",
      xbError: "",
      newBean: blankBean(),
      newGreenBean: blankGreenBean(),
      newBeanBatch: blankBeanBatch(),
      newRoast: blankRoast(),
      editRoast: blankRoast(),
      newCupping: blankCupping(),
      newBrew: { bean_id: "", brew_date: new Date().toISOString().slice(0, 10), data: blankBrewData() },
      stockAdjustment: { bean: null, mode: "add", net_weight: "", price_total: "" },
      greenStockAdjustment: { bean: null, mode: "add", total_weight: "" },
      beanDrafts: {},
      greenDrafts: {},
      brewDrafts: {},
      roastLearningDrafts: {},
      roastFilters: {
        bean: "",
        date_from: "",
        date_to: "",
        load_min: "",
        load_max: "",
        development_min: "",
        development_max: "",
        loss_min: "",
        loss_max: "",
        score_min: "",
      },
      compareIds: [],
      batchCompareIds: [],
      rowMessage: {},
      formMessage: "",
      greenMessage: "",
      roastMessage: "",
      cuppingMessage: "",
      brewMessage: "",
      roastLevelOptions,
      changedVariableOptions,
      roastEventTypeOptions,
      cuppingScoreFields,
    };
  },
  computed: {
    xbBusy() {
      return this.xbChecking || this.xbSaving;
    },
    xbPayloadText() {
      return JSON.stringify(this.xbDraft);
    },
    xbIsValidated() {
      return this.xbValidation?.payload === this.xbPayloadText;
    },
    xbPourTotal() {
      return this.xbDraft.recipe.pours.reduce((sum, pour) =>
        sum + (typeof pour.volume === "number" && Number.isFinite(pour.volume) ? pour.volume : 0), 0);
    },
    xbRatio() {
      const dose = this.xbDraft.doseGrams;
      const water = this.xbDraft.recipe.grandWater;
      return typeof dose === "number" && dose > 0 && typeof water === "number" && water > 0
        ? `1:${Number((water / dose).toFixed(2))}` : "—";
    },
    recommendation() {
      return this.inventory.summary.recommendation;
    },
    currentBeans() {
      return this.inventory.items.filter((bean) => bean.net_weight === null || bean.net_weight > 0);
    },
    historyBeans() {
      return this.inventory.items.filter((bean) => bean.net_weight === 0);
    },
    visibleBeans() {
      return this.inventoryView === "history" ? this.historyBeans : this.currentBeans;
    },
    currentGreenBeans() {
      return this.greenInventory.items.filter((bean) => bean.total_weight > 0);
    },
    historyGreenBeans() {
      return this.greenInventory.items.filter((bean) => bean.total_weight === 0);
    },
    visibleGreenBeans() {
      return this.inventoryView === "history" ? this.historyGreenBeans : this.currentGreenBeans;
    },
    currentSummary() {
      return {
        total_net_weight: this.currentBeans.reduce((sum, bean) => sum + bean.net_weight, 0),
        total_cups: this.currentBeans.reduce((sum, bean) => sum + bean.cups, 0),
      };
    },
    greenSummary() {
      return {
        total_weight: this.currentGreenBeans.reduce((sum, bean) => sum + bean.total_weight, 0),
        active_count: this.currentGreenBeans.length,
      };
    },
    filteredRoasts() {
      return this.roasts.filter((roast) => {
        const filters = this.roastFilters;
        const beanText = [
          roast.bean_name_snapshot,
          roast.bean_origin,
          roast.bean_process,
          roast.bean_variety,
          roast.profile_name,
        ].join(" ").toLowerCase();
        if (filters.bean && !beanText.includes(filters.bean.toLowerCase())) return false;
        if (filters.date_from && roast.roast_date < filters.date_from) return false;
        if (filters.date_to && roast.roast_date > filters.date_to) return false;
        if (filters.load_min && Number(roast.batch_weight_g || 0) < Number(filters.load_min)) return false;
        if (filters.load_max && Number(roast.batch_weight_g || 0) > Number(filters.load_max)) return false;
        if (filters.development_min && Number(roast.development_time_sec || 0) < Number(filters.development_min)) return false;
        if (filters.development_max && Number(roast.development_time_sec || 0) > Number(filters.development_max)) return false;
        if (filters.loss_min && Number(roast.weight_loss_pct || 0) < Number(filters.loss_min)) return false;
        if (filters.loss_max && Number(roast.weight_loss_pct || 0) > Number(filters.loss_max)) return false;
        if (filters.score_min && Number(roast.latest_cupping?.overall || 0) < Number(filters.score_min)) return false;
        return true;
      });
    },
    selectedRoasts() {
      const selected = new Set(this.compareIds.map((id) => Number(id)));
      return this.roasts.filter((roast) => selected.has(Number(roast.id)));
    },
    currentBatchRoasts() {
      return this.beanBatchDetail?.roasts || [];
    },
    selectedBatchRoasts() {
      const selected = new Set(this.batchCompareIds.map((id) => Number(id)));
      return this.currentBatchRoasts.filter((roast) => selected.has(Number(roast.id)));
    },
    roastPreviewMetrics() {
      return this.calculatePreviewMetrics(this.roastForm);
    },
    roastForm() {
      return this.view === "roast-edit" ? this.editRoast : this.newRoast;
    },
    roastFormTitle() {
      return this.view === "roast-edit" ? "修改烘焙记录" : "新增本批次烘焙";
    },
    roastSubmitLabel() {
      return this.view === "roast-edit" ? "保存修改" : "保存烘焙记录";
    },
    availableGreenBeansForRoast() {
      return this.view === "roast-edit" ? this.greenInventory.items : this.currentGreenBeans;
    },
    recommendationName() {
      return this.recommendation ? this.recommendation.name : "暂无推荐";
    },
    recommendationMeta() {
      if (!this.recommendation) return "黄金赏味期里会随机推荐一支";
      return `${this.recommendation.resting_days} 天 · ${this.recommendation.cups} 杯 · ${this.money(this.recommendation.price_per_gram)}/g`;
    },
  },
  async mounted() {
    if (this.view === "tastings") return;
    if (this.view === "xb-recipes") {
      await this.loadXbRecipes();
      return;
    }
    await this.loadInventory();
    await this.loadGreenInventory();
    await this.loadBeanBatches();
    await this.loadRoasts();
    if (this.routeBeanBatchId) {
      await this.loadBeanBatchDetail(this.routeBeanBatchId);
      if (this.view === "bean-roast-new") this.prepareRoastForBatch();
    }
    if (this.routeRoastId) {
      await this.loadRoastDetail(this.routeRoastId);
    }
    await this.loadBrews();
  },
  methods: {
    fieldName,
    fieldLabel,
    async loadXbRecipes() {
      if (this.xbLoading) return;
      this.xbLoading = true;
      this.xbListError = "";
      try {
        const result = await xbRequest("/api/xb-recipes");
        this.xbRecipes = result.items;
        this.xbFileErrors = (result.errors || []).map((entry) => ({
          ...entry, error: xbErrorMessage(entry.error),
        }));
      } catch (error) {
        this.xbListError = `配方列表读取失败：${error.message}`;
      } finally {
        this.xbLoading = false;
      }
    },
    newXbRecipe() {
      if (this.xbBusy) return;
      this.xbDraft = blankXbRecipe();
      this.xbName = "";
      this.xbSourceName = "";
      this.xbValidation = null;
      this.xbMessage = "";
      this.xbError = "";
      this.$nextTick(() => this.$refs.xbName?.focus());
    },
    copyXbRecipe(item) {
      if (this.xbBusy) return;
      this.xbDraft = clone(item.recipe);
      this.xbSourceName = item.name;
      const match = item.name.match(/^(.*)-v(\d+)$/i);
      const base = match ? match[1] : item.name;
      let version = match ? Number(match[2]) + 1 : 2;
      const names = new Set([...this.xbRecipes.map((recipe) => recipe.name),
        ...this.xbFileErrors.map((entry) => entry.filename.replace(/\.recipe\.json$/, ""))]);
      while (names.has(`${base}-v${version}`)) version += 1;
      this.xbName = `${base}-v${version}`;
      this.xbValidation = null;
      this.xbMessage = "已复制参数，请调整后另存为新配方。";
      this.xbError = "";
      this.$nextTick(() => {
        this.$refs.xbEditor?.scrollIntoView({ behavior: "smooth", block: "start" });
        this.$refs.xbName?.focus({ preventScroll: true });
      });
    },
    addXbPour() {
      if (!this.xbBusy && this.xbDraft.recipe.pours.length < 9) {
        this.xbDraft.recipe.pours.push(blankXbPour());
        this.xbError = "";
        this.xbMessage = "";
      }
    },
    removeXbPour(index) {
      if (!this.xbBusy && this.xbDraft.recipe.pours.length > 1) {
        this.xbDraft.recipe.pours.splice(index, 1);
        this.xbError = "";
        this.xbMessage = "";
      }
    },
    xbPattern(value) {
      return ["中心", "环绕", "螺旋"][value] || "未知";
    },
    xbTemperature(value) {
      if (value === 20) return "常温 RT";
      if (value === 98) return "BP";
      return `${value}℃`;
    },
    async checkXbRecipe() {
      if (this.xbBusy) return;
      this.xbChecking = true;
      this.xbError = "";
      this.xbMessage = "";
      this.xbValidation = null;
      const payload = this.xbPayloadText;
      try {
        const result = await xbRequest("/api/xb-recipes/validate", { method: "POST", body: payload });
        this.xbValidation = { payload, sha256: result.sha256 };
      } catch (error) {
        this.xbError = `配方检查未通过：${error.message}`;
      } finally {
        this.xbChecking = false;
      }
    },
    async saveXbRecipe() {
      if (this.xbBusy) return;
      this.xbError = "";
      this.xbMessage = "";
      const name = this.xbName;
      if (!/^[A-Za-z0-9\u3400-\u9fff][A-Za-z0-9\u3400-\u9fff_-]{0,79}$/.test(name) || name.toLowerCase() === "validate") {
        this.xbError = "名称请使用1–80个中文、英文字母、数字、短横线或下划线，并以中文、字母或数字开头。validate 为保留名称。";
        return;
      }
      const payload = this.xbPayloadText;
      this.xbSaving = true;
      try {
        const result = await xbRequest(`/api/xb-recipes/${encodeURIComponent(name)}`, {
          method: "POST", body: payload,
        });
        this.xbValidation = { payload, sha256: result.item.sha256 };
        this.xbMessage = `已保存「${result.item.name}」。继续调整时，请使用新名称另存。`;
        await this.loadXbRecipes();
      } catch (error) {
        this.xbError = error.status
          ? `保存失败：${error.message}`
          : `保存结果暂未确认：${error.message} 当前输入已保留，请刷新列表核对同名配方后再操作。`;
        if (!error.status) await this.loadXbRecipes();
      } finally {
        this.xbSaving = false;
      }
    },
    exportXbRecipe(item) {
      const link = document.createElement("a");
      // Download the saved bytes; JSON.stringify would change 3.0 to 3 and
      // invalidate the historical review fingerprint despite equal values.
      link.href = `/api/xb-recipes/${encodeURIComponent(item.name)}/download`;
      link.download = item.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
    },
    money(value) {
      return value == null ? "待补" : `¥${Number(value || 0).toFixed(2)}`;
    },
    display(value) {
      if (Array.isArray(value)) return value.length ? value.join("、") : "未填写";
      return value || "未填写";
    },
    number(value, suffix = "") {
      if (value === null || value === undefined || value === "") return "未填写";
      const number = Number(value);
      if (Number.isNaN(number)) return this.display(value);
      return `${Number.isInteger(number) ? number : number.toFixed(2)}${suffix}`;
    },
    formatSeconds(value) {
      if (value === null || value === undefined || value === "") return "未填写";
      const seconds = Number(value);
      if (Number.isNaN(seconds)) return "未填写";
      const minutes = Math.floor(seconds / 60);
      const rest = Math.round(seconds % 60).toString().padStart(2, "0");
      return `${minutes}:${rest}`;
    },
    inputSeconds(value) {
      if (value === null || value === undefined || value === "") return "";
      const seconds = Number(value);
      if (Number.isNaN(seconds)) return value;
      const minutes = Math.floor(seconds / 60);
      const rest = Math.round(seconds % 60).toString().padStart(2, "0");
      return `${minutes}:${rest}`;
    },
    parseTimeInput(value) {
      if (value === null || value === undefined || String(value).trim() === "") return null;
      const text = String(value).trim();
      if (text.includes(":")) {
        const [minutes, seconds] = text.split(":").map((part) => Number(part));
        if (!Number.isFinite(minutes) || !Number.isFinite(seconds) || seconds < 0 || seconds >= 60) return null;
        return minutes * 60 + seconds;
      }
      const seconds = Number(text);
      return Number.isFinite(seconds) ? seconds : null;
    },
    calculatePreviewMetrics(roast) {
      const batch = Number(roast.batch_weight_g || 0);
      const roasted = roast.roasted_weight_g === "" ? null : Number(roast.roasted_weight_g || 0);
      const yellow = this.parseTimeInput(roast.actual_yellow_time_s || roast.yellow_time_sec);
      const fc = this.parseTimeInput(roast.actual_first_crack_time_s || roast.first_crack_time_sec);
      const drop = this.parseTimeInput(roast.actual_drop_time_s || roast.drop_time_sec);
      const metrics = {
        weight_loss_pct: null,
        development_time_s: null,
        dtr_pct: null,
        dehydration_duration_s: yellow,
        maillard_duration_s: null,
      };
      if (batch > 0 && roasted !== null && roasted <= batch) {
        metrics.weight_loss_pct = ((batch - roasted) / batch) * 100;
      }
      if (fc !== null && drop !== null && drop > fc) {
        metrics.development_time_s = drop - fc;
        metrics.dtr_pct = drop > 0 ? (metrics.development_time_s / drop) * 100 : null;
      }
      if (yellow !== null && fc !== null && fc > yellow) {
        metrics.maillard_duration_s = fc - yellow;
      }
      return metrics;
    },
    optionLabel(options, value) {
      return options.find((option) => option[0] === value)?.[1] || this.display(value);
    },
    roastLevelLabel(value) {
      return this.optionLabel(roastLevelOptions, value || "unknown");
    },
    eventTypeLabel(value) {
      return this.optionLabel(roastEventTypeOptions, value);
    },
    roastScore(roast) {
      return roast.latest_cupping?.overall ? `${roast.latest_cupping.overall}/5` : "未杯测";
    },
    roastDraft(roast) {
      return {
        ...blankRoast(),
        roast_date: roast.roast_date || "",
        bean_id: roast.bean_id ? String(roast.bean_id) : "",
        bean_batch_id: roast.bean_batch_id ? String(roast.bean_batch_id) : "",
        bean_name_snapshot: roast.bean_name_snapshot || "",
        bean_origin: roast.bean_origin || "",
        bean_process: roast.bean_process || "",
        bean_variety: roast.bean_variety || "",
        roaster_model: roast.roaster_model || "Santoker Cube10",
        roast_label: roast.roast_label || "",
        batch_weight_g: roast.batch_weight_g ?? "",
        roasted_weight_g: roast.roasted_weight_g ?? "",
        cupping_reserved_g: roast.cupping_reserved_g ?? 8.25,
        create_roasted_batch: Boolean(roast.roasted_bean_id),
        profile_name: roast.profile_name || "",
        charge_temp_c: roast.charge_temp_c ?? "",
        preheat_temp_c: roast.preheat_temp_c ?? "",
        ambient_temp_c: roast.ambient_temp_c ?? "",
        fan_start: roast.fan_start ?? "",
        heat_start: roast.heat_start ?? "",
        operation_plan: roast.operation_plan || "",
        plan_yellow_time_s: this.inputSeconds(roast.plan_yellow_time_s),
        plan_yellow_temp_c: roast.plan_yellow_temp_c ?? "",
        plan_first_crack_time_s: this.inputSeconds(roast.plan_first_crack_time_s),
        plan_first_crack_temp_c: roast.plan_first_crack_temp_c ?? "",
        plan_drop_time_s: this.inputSeconds(roast.plan_drop_time_s),
        plan_drop_temp_c: roast.plan_drop_temp_c ?? "",
        plan_note: roast.plan_note || "",
        yellow_time_sec: this.inputSeconds(roast.yellow_time_sec),
        yellow_temp_c: roast.yellow_temp_c ?? "",
        first_crack_time_sec: this.inputSeconds(roast.first_crack_time_sec),
        first_crack_temp_c: roast.first_crack_temp_c ?? "",
        drop_time_sec: this.inputSeconds(roast.drop_time_sec),
        drop_temp_c: roast.drop_temp_c ?? "",
        actual_yellow_time_s: this.inputSeconds(roast.actual_yellow_time_s ?? roast.yellow_time_sec),
        actual_yellow_temp_c: roast.actual_yellow_temp_c ?? roast.yellow_temp_c ?? "",
        actual_first_crack_time_s: this.inputSeconds(roast.actual_first_crack_time_s ?? roast.first_crack_time_sec),
        actual_first_crack_temp_c: roast.actual_first_crack_temp_c ?? roast.first_crack_temp_c ?? "",
        actual_drop_time_s: this.inputSeconds(roast.actual_drop_time_s ?? roast.drop_time_sec),
        actual_drop_temp_c: roast.actual_drop_temp_c ?? roast.drop_temp_c ?? "",
        control_log: roast.control_log || "",
        roast_notes: roast.roast_notes || "",
        experiment_goal: roast.experiment_goal || "",
        changed_variable: roast.changed_variable || "",
        hypothesis: roast.hypothesis || "",
        result_summary: roast.result_summary || "",
        next_adjustment: roast.next_adjustment || "",
        roast_level: roast.roast_level || "unknown",
        color_note: roast.color_note || "",
        aroma_note: roast.aroma_note || "",
        defect_flags: roast.defect_flags || "",
        general_notes: roast.general_notes || "",
        learning_note: roast.learning_note || "",
        cupping_date: roast.cupping_date || "",
        cupping_score: roast.cupping_score ?? "",
        cupping_notes: roast.cupping_notes || "",
        defects: roast.defects || "",
        events: roast.events?.length ? roast.events.map((event) => ({
          event_type: event.event_type || "note",
          time_sec: this.inputSeconds(event.time_sec),
          temp_c: event.temp_c ?? "",
          heat_setting: event.heat_setting ?? "",
          fan_setting: event.fan_setting ?? "",
          note: event.note || "",
        })) : [blankRoastEvent()],
      };
    },
    selectedGreenBean() {
      const id = this.roastForm.bean_batch_id || this.roastForm.bean_id;
      return this.greenInventory.items.find((bean) => Number(bean.id) === Number(id));
    },
    applyGreenSnapshot() {
      const bean = this.selectedGreenBean();
      if (!bean) return;
      this.roastForm.bean_batch_id = String(bean.id);
      this.roastForm.bean_id = String(bean.id);
      this.roastForm.bean_name_snapshot = bean.display_name;
      this.roastForm.bean_origin = bean.origin || [bean.region, bean.estate].filter(Boolean).join(" / ");
      this.roastForm.bean_process = bean.process;
      this.roastForm.bean_variety = bean.variety_name || bean.bean_type;
    },
    async copyText(text) {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        return;
      }

      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.setAttribute("readonly", "");
      textarea.style.position = "fixed";
      textarea.style.left = "-9999px";
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
    },
    buildBrewExportText(brew) {
      const bean = brew.bean || {};
      const lines = [
        "咖啡冲煮记录",
        "",
        "【豆子信息】",
        `名称：${this.display(bean.name)}`,
        `烘焙商：${this.display(bean.roaster)}`,
        `烘焙商推荐参数：${this.display(bean.roaster_recommendation)}`,
        `国家：${this.display(bean.country)}`,
        `产区：${this.display(bean.region)}`,
        `庄园/生产者：${this.display(bean.producer)}`,
        `地块/批次：${this.display(bean.lot_info)}`,
        `豆种名称：${this.display(bean.variety_name)}`,
        `处理法：${this.display(bean.process)}`,
        `烘焙日期：${this.display(bean.roast_date)}`,
        `保存状态：${this.display(bean.storage_state)}`,
        "",
        "【冲煮基础】",
        `冲煮日期：${this.display(brew.brew_date)}`,
        `烘焙度（自评0-10）：${this.display(brew.data.bean_context.roast_degree)}`,
        `回温时间：${this.display(brew.data.bean_context.warming_time)}`,
      ];

      for (const section of brewSections) {
        const sectionLines = [];
        for (const field of section.fields) {
          const value = brew.data[section.key]?.[fieldName(field)];
          if (hasExportValue(value)) {
            sectionLines.push(`${fieldLabel(field)}：${formatExportValue(value)}`);
          }
        }
        if (sectionLines.length) {
          lines.push("", `【${section.title}】`, ...sectionLines);
        }
      }

      return lines.join("\n");
    },
    buildBrewMarkdown(brew, index) {
      const bean = brew.bean || {};
      const lines = [
        `## ${index}. ${this.display(brew.brew_date)} - ${this.display(bean.name)}`,
        "",
        "### 豆子信息",
        `- 名称：${this.display(bean.name)}`,
        `- 烘焙商：${this.display(bean.roaster)}`,
        `- 烘焙商推荐参数：${this.display(bean.roaster_recommendation)}`,
        `- 国家：${this.display(bean.country)}`,
        `- 产区：${this.display(bean.region)}`,
        `- 庄园/生产者：${this.display(bean.producer)}`,
        `- 地块/批次：${this.display(bean.lot_info)}`,
        `- 豆种名称：${this.display(bean.variety_name)}`,
        `- 处理法：${this.display(bean.process)}`,
        `- 烘焙日期：${this.display(bean.roast_date)}`,
        `- 保存状态：${this.display(bean.storage_state)}`,
        "",
        "### 冲煮基础",
        `- 冲煮日期：${this.display(brew.brew_date)}`,
        `- 烘焙度（自评0-10）：${this.display(brew.data.bean_context.roast_degree)}`,
        `- 回温时间：${this.display(brew.data.bean_context.warming_time)}`,
      ];

      for (const section of brewSections) {
        const sectionLines = [];
        for (const field of section.fields) {
          const value = brew.data[section.key]?.[fieldName(field)];
          if (hasExportValue(value)) {
            sectionLines.push(`- ${fieldLabel(field)}：${markdownValue(value)}`);
          }
        }
        if (sectionLines.length) {
          lines.push("", `### ${section.title}`, ...sectionLines);
        }
      }

      return lines.join("\n");
    },
    buildAllBrewsMarkdown() {
      const today = new Date().toISOString().slice(0, 10);
      const lines = [
        "# 咖啡冲煮记录导出",
        "",
        `导出日期：${today}`,
        `记录数量：${this.brews.length}`,
        "",
        "---",
        "",
      ];
      lines.push(this.brews.map((brew, index) => this.buildBrewMarkdown(brew, index + 1)).join("\n\n---\n\n"));
      return lines.join("\n");
    },
    downloadTextFile(filename, text) {
      const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    },
    findBean(id) {
      return this.inventory.items.find((bean) => Number(bean.id) === Number(id));
    },
    beanPayload(bean) {
      return {
        ...bean,
        total_weight: bean.total_weight === "" || bean.total_weight == null ? null : Number(bean.total_weight),
        net_weight: bean.net_weight === "" || bean.net_weight == null ? null : Number(bean.net_weight),
        price_total: bean.price_total === "" || bean.price_total == null ? null : Number(bean.price_total),
      };
    },
    greenPayload(bean) {
      return {
        ...bean,
        moisture_pct: bean.moisture_pct === "" ? "" : Number(bean.moisture_pct || 0),
        density: bean.density === "" ? "" : Number(bean.density || 0),
        purchase_weight_g: bean.purchase_weight_g === "" ? "" : Number(bean.purchase_weight_g || 0),
        remaining_green_weight_g: bean.remaining_green_weight_g === "" ? "" : Number(bean.remaining_green_weight_g || 0),
        total_weight: Number(bean.total_weight || 0),
      };
    },
    beanBatchPayload(batch) {
      return {
        ...batch,
        purchase_weight_g: batch.purchase_weight_g === "" ? "" : Number(batch.purchase_weight_g || 0),
        remaining_green_weight_g: batch.remaining_green_weight_g === "" ? "" : Number(batch.remaining_green_weight_g || 0),
      };
    },
    roastPayload(roast) {
      return {
        ...roast,
        bean_id: roast.bean_batch_id ? Number(roast.bean_batch_id) : roast.bean_id ? Number(roast.bean_id) : "",
        bean_batch_id: roast.bean_batch_id ? Number(roast.bean_batch_id) : roast.bean_id ? Number(roast.bean_id) : "",
        yellow_time_sec: roast.actual_yellow_time_s || roast.yellow_time_sec,
        yellow_temp_c: roast.actual_yellow_temp_c || roast.yellow_temp_c,
        first_crack_time_sec: roast.actual_first_crack_time_s || roast.first_crack_time_sec,
        first_crack_temp_c: roast.actual_first_crack_temp_c || roast.first_crack_temp_c,
        drop_time_sec: roast.actual_drop_time_s || roast.drop_time_sec,
        drop_temp_c: roast.actual_drop_temp_c || roast.drop_temp_c,
        create_roasted_batch: Boolean(roast.create_roasted_batch),
      };
    },
    cuppingPayload(cupping) {
      return { ...cupping };
    },
    beanDraft(bean) {
      return {
        name: bean.name,
        roaster: bean.roaster,
        roaster_recommendation: bean.roaster_recommendation,
        country: bean.country,
        region: bean.region,
        producer: bean.producer,
        lot_info: bean.lot_info,
        variety_name: bean.variety_name,
        roast_date: bean.roast_date,
        storage_state: bean.storage_state,
        process: bean.process,
        total_weight: bean.total_weight,
        net_weight: bean.net_weight,
        price_total: bean.price_total,
      };
    },
    greenDraft(bean) {
      return {
        name: bean.name,
        origin: bean.origin,
        crop_season: bean.crop_season,
        region: bean.region,
        bean_type: bean.bean_type,
        estate: bean.estate,
        variety_name: bean.variety_name,
        plot: bean.plot,
        batch: bean.batch,
        flavor_notes: bean.flavor_notes,
        supplier: bean.supplier,
        process: bean.process,
        moisture_pct: bean.moisture_pct,
        density: bean.density,
        purchase_weight_g: bean.purchase_weight_g,
        remaining_green_weight_g: bean.remaining_green_weight_g,
        notes: bean.notes,
        total_weight: bean.total_weight,
      };
    },
    brewPayload(brew) {
      return { bean_id: Number(brew.bean_id), brew_date: brew.brew_date, data: brew.data };
    },
    async loadInventory() {
      this.inventory = await api("/api/inventory");
      this.beanDrafts = Object.fromEntries(this.inventory.items.map((bean) => [bean.id, this.beanDraft(bean)]));
    },
    async loadGreenInventory() {
      this.greenInventory = await api("/api/green-inventory");
      this.greenDrafts = Object.fromEntries(this.greenInventory.items.map((bean) => [bean.id, this.greenDraft(bean)]));
    },
    async loadBeanBatches() {
      const data = await api("/api/bean-batches");
      this.beanBatches = data.items;
    },
    async loadBeanBatchDetail(id) {
      try {
        this.beanBatchDetail = await api(`/api/bean-batches/${id}`);
        this.batchCompareIds = this.beanBatchDetail.roasts.slice(0, 2).map((roast) => String(roast.id));
      } catch (error) {
        this.roastMessage = error.message;
      }
    },
    async loadRoasts() {
      const data = await api("/api/roasts");
      this.roasts = data.items;
      this.roastLearningDrafts = Object.fromEntries(this.roasts.map((roast) => [roast.id, roast.learning_note || ""]));
      if (!this.compareIds.length && this.view === "roast-compare") {
        this.compareIds = this.roasts.slice(0, 2).map((roast) => String(roast.id));
      }
    },
    async loadRoastDetail(id) {
      try {
        this.roastDetail = await api(`/api/roasts/${id}`);
        this.editRoast = this.roastDraft(this.roastDetail);
      } catch (error) {
        this.roastMessage = error.message;
      }
    },
    async loadBrews() {
      const data = await api("/api/brews");
      this.brews = data.items;
      this.brewDrafts = Object.fromEntries(this.brews.map((brew) => [brew.id, clone({
        bean_id: String(brew.bean_id),
        brew_date: brew.brew_date,
        data: brew.data,
      })]));
    },
    async createBean() {
      try {
        await api("/api/inventory", { method: "POST", body: JSON.stringify(this.beanPayload(this.newBean)) });
        this.newBean = blankBean();
        this.formMessage = "库存已保存";
        this.$refs.beanDialog.close();
        await this.loadInventory();
      } catch (error) {
        this.formMessage = error.message;
      }
    },
    openBeanDialog() {
      this.formMessage = "";
      this.$refs.beanDialog.showModal();
    },
    closeBeanDialog() {
      this.$refs.beanDialog.close();
    },
    async createGreenBean() {
      try {
        await api("/api/green-inventory", { method: "POST", body: JSON.stringify(this.greenPayload(this.newGreenBean)) });
        this.newGreenBean = blankGreenBean();
        this.greenMessage = "生豆库存已保存";
        this.$refs.greenDialog.close();
        await this.loadGreenInventory();
      } catch (error) {
        this.greenMessage = error.message;
      }
    },
    openGreenDialog() {
      this.greenMessage = "";
      this.$refs.greenDialog.showModal();
    },
    closeGreenDialog() {
      this.$refs.greenDialog.close();
    },
    async createBeanBatch() {
      try {
        const result = await api("/api/bean-batches", {
          method: "POST",
          body: JSON.stringify(this.beanBatchPayload(this.newBeanBatch)),
        });
        this.newBeanBatch = blankBeanBatch();
        this.roastMessage = "生豆批次已创建";
        this.$refs.beanBatchDialog.close();
        await this.loadBeanBatches();
        location.href = `/beans/${result.item.id}`;
      } catch (error) {
        this.roastMessage = error.message;
      }
    },
    openBeanBatchDialog() {
      this.roastMessage = "";
      this.$refs.beanBatchDialog.showModal();
    },
    closeBeanBatchDialog() {
      this.$refs.beanBatchDialog.close();
    },
    prepareRoastForBatch() {
      if (!this.beanBatchDetail) return;
      this.newRoast = {
        ...blankRoast(),
        bean_id: String(this.beanBatchDetail.id),
        bean_batch_id: String(this.beanBatchDetail.id),
        bean_name_snapshot: this.beanBatchDetail.name,
        bean_origin: this.beanBatchDetail.origin || "",
        bean_process: this.beanBatchDetail.process || "",
        bean_variety: this.beanBatchDetail.variety || "",
      };
    },
    addRoastEvent() {
      this.roastForm.events.push(blankRoastEvent());
    },
    removeRoastEvent(index) {
      if (this.roastForm.events.length === 1) {
        this.roastForm.events = [blankRoastEvent()];
        return;
      }
      this.roastForm.events.splice(index, 1);
    },
    async submitRoast() {
      try {
        const isEdit = this.view === "roast-edit";
        const isBatchNew = this.view === "bean-roast-new";
        const targetUrl = isEdit
          ? `/api/roasts/${this.routeRoastId}`
          : isBatchNew
            ? `/api/bean-batches/${this.routeBeanBatchId}/roasts`
            : "/api/roasts";
        const result = await api(targetUrl, {
          method: isEdit ? "PUT" : "POST",
          body: JSON.stringify(this.roastPayload(this.roastForm)),
        });
        this.roastMessage = isEdit ? "烘焙记录已更新" : `烘焙记录 #${result.item.id} 已保存`;
        await this.loadGreenInventory();
        await this.loadInventory();
        await this.loadBeanBatches();
        location.href = isBatchNew
          ? `/beans/${this.routeBeanBatchId}`
          : isEdit && result.item.bean_batch_id
            ? `/beans/${result.item.bean_batch_id}`
            : `/roasts/${result.item.id}`;
      } catch (error) {
        this.roastMessage = error.message;
      }
    },
    async updateRoastLearningNote(roast) {
      try {
        const result = await api(`/api/roasts/${roast.id}/learning-note`, {
          method: "PUT",
          body: JSON.stringify({ learning_note: this.roastLearningDrafts[roast.id] || "" }),
        });
        Object.assign(roast, result.item);
        this.roastLearningDrafts[roast.id] = result.item.learning_note || "";
        this.rowMessage[`roast-learning-${roast.id}`] = "心得已保存";
      } catch (error) {
        this.rowMessage[`roast-learning-${roast.id}`] = error.message;
      }
    },
    async createCupping() {
      try {
        await api(`/api/roasts/${this.routeRoastId}/cupping`, {
          method: "POST",
          body: JSON.stringify(this.cuppingPayload(this.newCupping)),
        });
        this.cuppingMessage = "杯测记录已保存";
        location.href = this.roastDetail?.bean_batch_id
          ? `/beans/${this.roastDetail.bean_batch_id}`
          : `/roasts/${this.routeRoastId}`;
      } catch (error) {
        this.cuppingMessage = error.message;
      }
    },
    toggleCompare(id, event) {
      const value = String(id);
      if (event.target.checked) {
        if (this.compareIds.length >= 4) {
          event.target.checked = false;
          this.roastMessage = "最多选择 4 锅对比";
          return;
        }
        if (!this.compareIds.includes(value)) this.compareIds.push(value);
        return;
      }
      this.compareIds = this.compareIds.filter((item) => item !== value);
    },
    toggleBatchCompare(id, event) {
      const value = String(id);
      if (event.target.checked) {
        if (this.batchCompareIds.length >= 4) {
          event.target.checked = false;
          this.roastMessage = "最多选择 4 锅对比";
          return;
        }
        if (!this.batchCompareIds.includes(value)) this.batchCompareIds.push(value);
        return;
      }
      this.batchCompareIds = this.batchCompareIds.filter((item) => item !== value);
    },
    async updateBean(bean) {
      try {
        await api(`/api/inventory/${bean.id}`, {
          method: "PUT",
          body: JSON.stringify(this.beanPayload(this.beanDrafts[bean.id])),
        });
        this.rowMessage[bean.id] = "已保存";
        await this.loadInventory();
      } catch (error) {
        this.rowMessage[bean.id] = error.message;
      }
    },
    async updateGreenBean(bean) {
      try {
        await api(`/api/green-inventory/${bean.id}`, {
          method: "PUT",
          body: JSON.stringify(this.greenPayload(this.greenDrafts[bean.id])),
        });
        this.rowMessage[`green-${bean.id}`] = "已保存";
        await this.loadGreenInventory();
      } catch (error) {
        this.rowMessage[`green-${bean.id}`] = error.message;
      }
    },
    async deleteBean(bean) {
      if (!confirm(`确认删除 ${bean.name} 吗？`)) return;
      await api(`/api/inventory/${bean.id}`, { method: "DELETE" });
      await this.loadInventory();
    },
    async deleteGreenBean(bean) {
      if (!confirm(`确认删除 ${bean.display_name} 吗？`)) return;
      await api(`/api/green-inventory/${bean.id}`, { method: "DELETE" });
      await this.loadGreenInventory();
    },
    openStockDialog(bean, mode) {
      this.stockAdjustment = { bean, mode, net_weight: "", price_total: "" };
      this.rowMessage[`stock-${bean.id}`] = "";
      this.$refs.stockDialog.showModal();
    },
    openGreenStockDialog(bean, mode) {
      this.greenStockAdjustment = { bean, mode, total_weight: "" };
      this.rowMessage[`green-stock-${bean.id}`] = "";
      this.$refs.greenStockDialog.showModal();
    },
    closeStockDialog() {
      this.$refs.stockDialog.close();
    },
    closeGreenStockDialog() {
      this.$refs.greenStockDialog.close();
    },
    async saveStockAdjustment() {
      const { bean, mode, net_weight, price_total } = this.stockAdjustment;
      try {
        await api(`/api/inventory/${bean.id}/${mode}`, {
          method: "POST",
          body: JSON.stringify({
            net_weight: Number(net_weight || 0),
            price_total: mode === "add" ? Number(price_total || 0) : 0,
          }),
        });
        this.rowMessage[`stock-${bean.id}`] = mode === "add" ? "库存已增加" : "库存已减少";
        this.$refs.stockDialog.close();
        await this.loadInventory();
      } catch (error) {
        this.rowMessage[`stock-${bean.id}`] = error.message;
      }
    },
    async saveGreenStockAdjustment() {
      const { bean, mode, total_weight } = this.greenStockAdjustment;
      try {
        await api(`/api/green-inventory/${bean.id}/${mode}`, {
          method: "POST",
          body: JSON.stringify({ total_weight: Number(total_weight || 0) }),
        });
        this.rowMessage[`green-stock-${bean.id}`] = mode === "add" ? "生豆库存已增加" : "生豆库存已减少";
        this.$refs.greenStockDialog.close();
        await this.loadGreenInventory();
      } catch (error) {
        this.rowMessage[`green-stock-${bean.id}`] = error.message;
      }
    },
    async createBrew() {
      try {
        const result = await api("/api/brews", { method: "POST", body: JSON.stringify(this.brewPayload(this.newBrew)) });
        this.newBrew = { bean_id: "", brew_date: new Date().toISOString().slice(0, 10), data: blankBrewData() };
        this.brewMessage = `冲煮记录 #${result.item.id} 已保存`;
        this.$refs.brewDialog.close();
        await this.loadBrews();
      } catch (error) {
        this.brewMessage = error.message;
      }
    },
    openBrewDialog() {
      this.brewMessage = "";
      this.$refs.brewDialog.showModal();
    },
    closeBrewDialog() {
      this.$refs.brewDialog.close();
    },
    async updateBrew(brew) {
      try {
        await api(`/api/brews/${brew.id}`, {
          method: "PUT",
          body: JSON.stringify(this.brewPayload(this.brewDrafts[brew.id])),
        });
        this.rowMessage[`brew-${brew.id}`] = "已保存";
        await this.loadBrews();
      } catch (error) {
        this.rowMessage[`brew-${brew.id}`] = error.message;
      }
    },
    async exportBrew(brew) {
      try {
        await this.copyText(this.buildBrewExportText(brew));
        this.rowMessage[`brew-${brew.id}`] = "已复制导出内容";
      } catch (error) {
        this.rowMessage[`brew-${brew.id}`] = `复制失败：${error.message}`;
      }
    },
    exportBrewFromSummary(event, brew) {
      event.preventDefault();
      event.stopPropagation();
      this.exportBrew(brew);
    },
    exportAllBrews() {
      if (!this.brews.length) {
        this.brewMessage = "没有可导出的冲煮记录";
        return;
      }
      const today = new Date().toISOString().slice(0, 10);
      this.downloadTextFile(`coffee-brews-${today}.md`, this.buildAllBrewsMarkdown());
      this.brewMessage = "全部冲煮记录已导出";
    },
    async deleteBrew(brew) {
      if (!confirm(`确认删除 ${brew.brew_date} 的冲煮记录吗？`)) return;
      await api(`/api/brews/${brew.id}`, { method: "DELETE" });
      await this.loadBrews();
    },
  },
  template: `
    <main>
      <header class="topbar">
        <a class="brand" href="/">咖啡系统</a>
        <nav class="topnav">
          <a href="/" :class="{ active: view === 'inventory' }">咖啡豆库存</a>
          <a href="/green" :class="{ active: view === 'green' }">生豆库存</a>
          <a href="/roasts" :class="{ active: ['roasts', 'bean-batch-detail', 'bean-roast-new', 'roast-new', 'roast-edit', 'roast-detail', 'roast-cupping', 'roast-compare'].includes(view) }">烘焙记录</a>
          <a href="/brews" :class="{ active: view === 'brews' }">冲煮记录</a>
          <a href="/tastings" :class="{ active: view === 'tastings' }">个人品饮</a>
          <a href="/xb-recipes" :class="{ active: view === 'xb-recipes' }">xBloom 配方</a>
        </nav>
        <p>记录咖啡豆库存和冲煮日志。</p>
      </header>

      <div class="app-shell">
        <tasting-room v-if="view === 'tastings'"></tasting-room>
        <section v-else-if="view === 'xb-recipes'" class="xb-page" aria-labelledby="xb-page-title">
          <div class="panel-heading xb-page-heading">
            <div>
              <h1 id="xb-page-title">xBloom 配方</h1>
              <p>保存每一次参数选择。咖啡豆库存保存在本机 SQLite。</p>
            </div>
            <button type="button" class="secondary" @click="newXbRecipe" :disabled="xbBusy">新建配方</button>
          </div>

          <div class="xb-layout">
            <section class="panel xb-library" aria-labelledby="xb-library-title">
              <div class="panel-heading">
                <div><h2 id="xb-library-title">已保存配方</h2><p>{{ xbRecipes.length }} 份 · xBloom Studio / Omni</p></div>
                <button type="button" class="secondary" @click="loadXbRecipes" :disabled="xbLoading || xbBusy" :aria-busy="xbLoading">刷新</button>
              </div>
              <p v-if="xbListError" class="xb-error" role="alert">{{ xbListError }}</p>
              <p v-if="xbLoading && !xbRecipes.length" role="status">正在读取配方…</p>
              <p v-else-if="!xbRecipes.length && !xbListError" class="empty">还没有配方，在右侧填写第一份。</p>
              <div class="xb-recipe-list">
                <details v-for="item in xbRecipes" :key="item.name" class="xb-recipe-card">
                  <summary>
                    <strong>{{ item.name }}</strong>
                    <span>{{ item.recipe.doseGrams }}g / {{ item.recipe.recipe.grandWater }}ml · 研磨 {{ item.recipe.recipe.grinderSize }} · {{ item.recipe.recipe.pours.length }} 段</span>
                  </summary>
                  <p class="xb-recipe-meta">{{ item.recipe.recipe.rpm }} RPM · Omni 滤杯</p>
                  <ol class="xb-pour-summary">
                    <li v-for="(pour, index) in item.recipe.recipe.pours" :key="index">
                      <strong>第 {{ index + 1 }} 段 · {{ pour.volume }}ml</strong>
                      <span>{{ xbTemperature(pour.temperature) }} · {{ pour.flowRate }}ml/s · {{ xbPattern(pour.pattern) }} · 停顿 {{ pour.pausing }}秒</span>
                      <small>注水前振动：{{ pour.vibBefore ? '开' : '关' }} · 注水后振动：{{ pour.vibAfter ? '开' : '关' }}</small>
                    </li>
                  </ol>
                  <div class="xb-card-actions">
                    <button type="button" @click="copyXbRecipe(item)" :disabled="xbBusy">复制并调参</button>
                    <button type="button" class="secondary" @click="exportXbRecipe(item)">导出 JSON</button>
                  </div>
                </details>
              </div>
              <details v-if="xbFileErrors.length" class="xb-file-errors">
                <summary>{{ xbFileErrors.length }} 份文件未通过检查</summary>
                <p v-for="entry in xbFileErrors" :key="entry.filename"><strong>{{ entry.filename }}</strong><br>{{ entry.error }}</p>
              </details>
            </section>

            <section class="panel xb-editor" ref="xbEditor" aria-labelledby="xb-editor-title">
              <div class="panel-heading">
                <div><h2 id="xb-editor-title">{{ xbSourceName ? '调整并另存' : '创建配方' }}</h2>
                  <p v-if="xbSourceName">基于「{{ xbSourceName }}」，保存为新版本。</p>
                  <p v-else>填写参数与每段注水，保存时会自动检查。</p>
                </div>
                <span class="xb-check-status" :class="{ valid: xbIsValidated }">{{ xbIsValidated ? '格式检查通过' : '待检查' }}</span>
              </div>
              <form @submit.prevent="saveXbRecipe">
                <fieldset :disabled="xbBusy" class="xb-form-fields">
                  <label>配方名称
                    <input ref="xbName" v-model="xbName" required maxlength="80" placeholder="例如：水洗耶加-v1" autocomplete="off">
                    <small>支持中文、字母、数字、- 和 _；已有名称不能覆盖。</small>
                  </label>
                  <div class="xb-base-grid">
                    <label>粉量（g）<input v-model.number="xbDraft.doseGrams" type="number" min="5" max="18" step="1" required placeholder="5–18"></label>
                    <label>总注水量（ml）<input v-model.number="xbDraft.recipe.grandWater" type="number" min="1" max="500" step="1" required placeholder="最多500"></label>
                    <label>研磨档位<input v-model.number="xbDraft.recipe.grinderSize" type="number" min="1" max="80" step="1" required placeholder="1–80"></label>
                    <label>研磨转速（RPM）<select v-model.number="xbDraft.recipe.rpm"><option v-for="rpm in [60,70,80,90,100,110,120]" :key="rpm" :value="rpm">{{ rpm }}</option></select></label>
                  </div>
                  <div class="xb-ratio-line"><span>滤杯：Omni</span><span>粉水比 {{ xbRatio }}</span><span :class="{ 'xb-total-mismatch': xbDraft.recipe.grandWater !== '' && xbPourTotal !== xbDraft.recipe.grandWater }">分段合计 {{ xbPourTotal }}ml</span></div>
                  <div class="xb-pours-heading"><h3>分段注水</h3><span>{{ xbDraft.recipe.pours.length }} / 9 段</span></div>
                  <fieldset v-for="(pour, index) in xbDraft.recipe.pours" :key="index" class="xb-pour-editor">
                    <legend>第 {{ index + 1 }} 段</legend>
                    <div class="xb-pour-grid">
                      <label>注水量（ml）<input v-model.number="pour.volume" :aria-label="'第' + (index + 1) + '段注水量（ml）'" type="number" min="1" max="500" step="1" required></label>
                      <label>水温<select v-model.number="pour.temperature" :aria-label="'第' + (index + 1) + '段水温'" required><option value="" disabled>选择水温</option><option :value="20">常温 RT</option><option v-for="temp in 56" :key="temp" :value="temp + 39">{{ temp + 39 }}℃</option><option :value="98">BP</option></select></label>
                      <label>流速（ml/s）<select v-model.number="pour.flowRate" :aria-label="'第' + (index + 1) + '段流速'"><option v-for="flow in [3.0,3.1,3.2,3.3,3.4,3.5]" :key="flow" :value="flow">{{ flow.toFixed(1) }}</option></select></label>
                      <label>注水轨迹<select v-model.number="pour.pattern" :aria-label="'第' + (index + 1) + '段注水轨迹'"><option :value="0">中心</option><option :value="1">环绕</option><option :value="2">螺旋</option></select></label>
                      <label>注水后停顿（秒）<input v-model.number="pour.pausing" :aria-label="'第' + (index + 1) + '段停顿（秒）'" type="number" min="0" max="59" step="1" required></label>
                    </div>
                    <div class="xb-pour-footer">
                      <label><input v-model="pour.vibBefore" type="checkbox" :aria-label="'第' + (index + 1) + '段注水前振动'"> 注水前振动</label>
                      <label><input v-model="pour.vibAfter" type="checkbox" :aria-label="'第' + (index + 1) + '段注水后振动'"> 注水后振动</label>
                      <button type="button" class="secondary xb-remove-pour" @click="removeXbPour(index)" :disabled="xbDraft.recipe.pours.length <= 1" :aria-label="'移除第' + (index + 1) + '段'">移除</button>
                    </div>
                  </fieldset>
                  <button type="button" class="secondary xb-add-pour" @click="addXbPour" :disabled="xbDraft.recipe.pours.length >= 9">＋ 添加一段</button>
                  <div class="xb-editor-actions">
                    <button type="button" class="secondary" @click="checkXbRecipe" :aria-busy="xbChecking">检查配方</button>
                    <button type="submit" :aria-busy="xbSaving">保存新配方</button>
                  </div>
                </fieldset>
                <p v-if="xbError" class="xb-error" role="alert">{{ xbError }}</p>
                <p v-if="xbMessage" class="xb-success" role="status">{{ xbMessage }}</p>
              </form>
            </section>
          </div>
        </section>

        <section v-if="view === 'inventory'" class="stats-grid">
          <article class="stat-card">
            <span class="muted">总库存杯数</span>
            <strong>{{ currentSummary.total_cups }} 杯</strong>
            <small>已知余量 {{ currentSummary.total_net_weight }} g · {{ currentBeans.filter(b => b.net_weight == null).length }} 条待补重量</small>
          </article>
          <article class="stat-card">
            <span class="muted">今日推荐</span>
            <strong>{{ recommendationName }}</strong>
            <small>{{ recommendationMeta }}</small>
          </article>
        </section>

        <section v-if="view === 'green'" class="stats-grid">
          <article class="stat-card">
            <span class="muted">生豆总库存</span>
            <strong>{{ greenSummary.total_weight }} g</strong>
            <small>{{ greenSummary.active_count }} 条当前库存</small>
          </article>
          <article class="stat-card">
            <span class="muted">管理方式</span>
            <strong>生豆库存</strong>
            <small>可展开记录原地修改，也可快速增减克数</small>
          </article>
        </section>

        <section v-if="['roasts', 'bean-batch-detail', 'bean-roast-new', 'roast-new', 'roast-edit', 'roast-detail', 'roast-cupping', 'roast-compare'].includes(view)" class="stats-grid">
          <article class="stat-card">
            <span class="muted">生豆批次</span>
            <strong>{{ beanBatches.length }} 批</strong>
            <small>以批次为入口管理多锅烘焙</small>
          </article>
          <article class="stat-card">
            <span class="muted">最近一锅</span>
            <strong>{{ roasts[0]?.bean_name_snapshot || '暂无烘焙' }}</strong>
            <small>{{ roasts[0] ? roasts[0].roast_date + ' · DTR ' + number(roasts[0].dtr_pct, '%') : '新建后自动计算指标' }}</small>
          </article>
        </section>

      <section v-if="view === 'inventory'">
        <section class="panel">
          <div class="panel-heading">
            <div>
              <h2>库存列表</h2>
              <p>点击条目可展开信息并直接原地修改。</p>
            </div>
            <button type="button" class="primary" @click="openBeanDialog">新增咖啡豆</button>
          </div>

          <nav class="sub-tabs">
            <button type="button" :class="{ active: inventoryView === 'current' }" @click="inventoryView = 'current'">
              当前库存 {{ currentBeans.length }}
            </button>
            <button type="button" :class="{ active: inventoryView === 'history' }" @click="inventoryView = 'history'">
              历史库存 {{ historyBeans.length }}
            </button>
          </nav>

          <div v-if="!visibleBeans.length" class="empty">
            {{ inventoryView === 'history' ? '还没有历史库存' : '还没有当前库存记录' }}
          </div>

          <div class="list">
            <details v-for="bean in visibleBeans" :key="bean.id" class="record">
              <summary class="summary-row inventory-summary-row">
                <div class="bean-title">
                  <strong>{{ bean.roaster || "烘焙商待补" }} · {{ bean.name }}</strong>
                  <span class="badge">{{ bean.freshness_label }}</span>
                </div>
                <span><span class="muted">克价</span><span class="value">{{ money(bean.price_per_gram) }}/g</span></span>
                <span><span class="muted">烘焙日</span><span class="value">{{ bean.roast_date || "待补" }}</span></span>
                <span><span class="muted">总克数</span><span class="value">{{ number(bean.total_weight, " g") }}</span></span>
                <span><span class="muted">剩余克数</span><span class="value">{{ number(bean.net_weight, " g") }}</span></span>
              </summary>

              <div class="section info-grid">
                <div class="tag"><span class="muted">处理法</span><span>{{ display(bean.process) }}</span></div>
                <div class="tag"><span class="muted">豆种</span><span>{{ display(bean.variety_name) }}</span></div>
                <div class="tag"><span class="muted">总克数</span><span>{{ number(bean.total_weight, " g") }}</span></div>
                <div class="tag"><span class="muted">剩余克数</span><span>{{ number(bean.net_weight, " g") }}</span></div>
                <div class="tag" v-if="bean.source_flavor?.length"><span class="muted">标签风味</span><span>{{ bean.source_flavor.join("、") }}</span></div>
                <div class="tag full" v-if="bean.source_notes"><span class="muted">原始标签备注</span><span>{{ bean.source_notes }}</span></div>
                <div class="tag"><span class="muted">烘焙商推荐参数</span><span>{{ display(bean.roaster_recommendation) }}</span></div>
                <div class="tag"><span class="muted">烘焙日</span><span>{{ bean.roast_date || "待补" }}</span></div>
                <div class="tag"><span class="muted">保存状态</span><span>{{ bean.storage_state }}</span></div>
                <div class="tag"><span class="muted">单价</span><span>{{ money(bean.price_per_gram) }}/g</span></div>
                <div class="tag"><span class="muted">剩余金额</span><span>{{ money(bean.price_total) }}</span></div>
              </div>

              <form class="section" @submit.prevent="updateBean(bean)">
                <div class="actions stock-actions">
                  <button type="button" class="secondary" @click="openStockDialog(bean, 'add')">加库存</button>
                  <button type="button" class="secondary" @click="openStockDialog(bean, 'deduct')">减库存</button>
                  <span class="message">{{ rowMessage['stock-' + bean.id] }}</span>
                </div>
                <field-grid :fields="bean.source_notes != null ? importedBeanFields : beanFields" :model="beanDrafts[bean.id]"></field-grid>
                <div class="actions">
                  <button>保存修改</button>
                  <button type="button" class="secondary danger" @click="deleteBean(bean)">删除</button>
                  <span class="message">{{ rowMessage[bean.id] }}</span>
                </div>
              </form>
            </details>
          </div>
        </section>

        <dialog ref="beanDialog" class="form-dialog">
          <article>
            <header>
              <button aria-label="关闭" rel="prev" type="button" @click="closeBeanDialog"></button>
              <h2>新增咖啡豆</h2>
            </header>
            <form @submit.prevent="createBean">
              <field-grid :fields="beanFields" :model="newBean"></field-grid>
              <footer class="actions">
                <button type="submit">保存到库存</button>
                <button type="button" class="secondary" @click="closeBeanDialog">取消</button>
                <span class="message">{{ formMessage }}</span>
              </footer>
            </form>
          </article>
        </dialog>

        <dialog ref="stockDialog" class="stock-dialog">
          <article>
            <header>
              <button aria-label="关闭" rel="prev" type="button" @click="closeStockDialog"></button>
              <h2>{{ stockAdjustment.mode === 'add' ? '增加库存' : '减少库存' }}</h2>
              <p v-if="stockAdjustment.bean">{{ stockAdjustment.bean.name }}</p>
            </header>
            <form @submit.prevent="saveStockAdjustment">
              <div class="form-grid">
                <label>
                  净含量（g）
                  <input v-model="stockAdjustment.net_weight" type="number" min="0" step="1" required>
                </label>
                <label v-if="stockAdjustment.mode === 'add'">
                  价格（元）
                  <input v-model="stockAdjustment.price_total" type="number" min="0" step="0.01" required>
                </label>
              </div>
              <footer class="actions">
                <button type="submit">{{ stockAdjustment.mode === 'add' ? '确认增加' : '确认减少' }}</button>
                <button type="button" class="secondary" @click="closeStockDialog">取消</button>
                <span v-if="stockAdjustment.bean" class="message">{{ rowMessage['stock-' + stockAdjustment.bean.id] }}</span>
              </footer>
            </form>
          </article>
        </dialog>
      </section>

      <section v-else-if="view === 'green'">
        <section class="panel">
          <div class="panel-heading">
            <div>
              <h2>生豆库存列表</h2>
              <p>点击条目展开后可原地编辑，也可以用小按钮快速增减库存克数。</p>
            </div>
            <button type="button" class="primary" @click="openGreenDialog">新增生豆</button>
          </div>

          <nav class="sub-tabs">
            <button type="button" :class="{ active: inventoryView === 'current' }" @click="inventoryView = 'current'">
              当前库存 {{ currentGreenBeans.length }}
            </button>
            <button type="button" :class="{ active: inventoryView === 'history' }" @click="inventoryView = 'history'">
              历史库存 {{ historyGreenBeans.length }}
            </button>
          </nav>

          <div v-if="!visibleGreenBeans.length" class="empty">
            {{ inventoryView === 'history' ? '还没有生豆历史库存' : '还没有生豆库存记录' }}
          </div>

          <div class="list">
            <details v-for="bean in visibleGreenBeans" :key="bean.id" class="record">
              <summary class="summary-row green-summary-row">
                <div class="bean-title">
                  <strong>{{ bean.display_name }}</strong>
                  <span class="badge">{{ bean.process || '未填处理法' }}</span>
                </div>
                <span><span class="muted">产季</span><span class="value">{{ display(bean.crop_season) }}</span></span>
                <span><span class="muted">生豆商</span><span class="value">{{ display(bean.supplier) }}</span></span>
                <span><span class="muted">总量</span><span class="value">{{ bean.total_weight }} g</span></span>
              </summary>

              <div class="section info-grid">
                <div class="tag"><span class="muted">产区</span><span>{{ display(bean.region) }}</span></div>
                <div class="tag"><span class="muted">庄园</span><span>{{ display(bean.estate) }}</span></div>
                <div class="tag"><span class="muted">豆种</span><span>{{ display(bean.bean_type) }}</span></div>
                <div class="tag"><span class="muted">地块</span><span>{{ display(bean.plot) }}</span></div>
                <div class="tag"><span class="muted">批次</span><span>{{ display(bean.batch) }}</span></div>
                <div class="tag"><span class="muted">含水率</span><span>{{ number(bean.moisture_pct, '%') }}</span></div>
                <div class="tag"><span class="muted">密度</span><span>{{ number(bean.density) }}</span></div>
                <div class="tag full"><span class="muted">风味描述</span><span>{{ display(bean.flavor_notes) }}</span></div>
              </div>

              <form class="section" @submit.prevent="updateGreenBean(bean)">
                <div class="actions stock-actions">
                  <button type="button" class="secondary" @click="openGreenStockDialog(bean, 'add')">加库存</button>
                  <button type="button" class="secondary" @click="openGreenStockDialog(bean, 'deduct')">减库存</button>
                  <span class="message">{{ rowMessage['green-stock-' + bean.id] }}</span>
                </div>
                <field-grid :fields="greenBeanFields" :model="greenDrafts[bean.id]"></field-grid>
                <div class="actions">
                  <button>保存修改</button>
                  <button type="button" class="secondary danger" @click="deleteGreenBean(bean)">删除</button>
                  <span class="message">{{ rowMessage['green-' + bean.id] }}</span>
                </div>
              </form>
            </details>
          </div>
        </section>

        <dialog ref="greenDialog" class="form-dialog">
          <article>
            <header>
              <button aria-label="关闭" rel="prev" type="button" @click="closeGreenDialog"></button>
              <h2>新增生豆</h2>
            </header>
            <form @submit.prevent="createGreenBean">
              <field-grid :fields="greenBeanFields" :model="newGreenBean"></field-grid>
              <footer class="actions">
                <button type="submit">保存到生豆库存</button>
                <button type="button" class="secondary" @click="closeGreenDialog">取消</button>
                <span class="message">{{ greenMessage }}</span>
              </footer>
            </form>
          </article>
        </dialog>

        <dialog ref="greenStockDialog" class="stock-dialog">
          <article>
            <header>
              <button aria-label="关闭" rel="prev" type="button" @click="closeGreenStockDialog"></button>
              <h2>{{ greenStockAdjustment.mode === 'add' ? '增加生豆库存' : '减少生豆库存' }}</h2>
              <p v-if="greenStockAdjustment.bean">{{ greenStockAdjustment.bean.display_name }}</p>
            </header>
            <form @submit.prevent="saveGreenStockAdjustment">
              <div class="form-grid">
                <label>
                  总量（g）
                  <input v-model="greenStockAdjustment.total_weight" type="number" min="0" step="1" required>
                </label>
              </div>
              <footer class="actions">
                <button type="submit">{{ greenStockAdjustment.mode === 'add' ? '确认增加' : '确认减少' }}</button>
                <button type="button" class="secondary" @click="closeGreenStockDialog">取消</button>
                <span v-if="greenStockAdjustment.bean" class="message">{{ rowMessage['green-stock-' + greenStockAdjustment.bean.id] }}</span>
              </footer>
            </form>
          </article>
        </dialog>
      </section>

      <section v-else-if="view === 'roasts'">
        <section class="panel">
          <div class="panel-heading">
            <div>
              <h2>生豆批次</h2>
              <p>先选一批豆子，再在同一批下面记录多锅烘焙、对比差异和沉淀下一锅思路。</p>
            </div>
            <div class="heading-actions">
              <button type="button" class="primary" @click="openBeanBatchDialog">新增生豆批次</button>
            </div>
          </div>

          <p class="message">{{ roastMessage }}</p>
          <div v-if="!beanBatches.length" class="empty">还没有生豆批次，先创建一批豆子。</div>
          <div v-else class="batch-grid">
            <article v-for="batch in beanBatches" :key="batch.id" class="batch-card">
              <div>
                <h3>{{ batch.name }}</h3>
                <p>{{ display(batch.origin) }} · {{ display(batch.process) }} · {{ display(batch.variety) }}</p>
              </div>
              <div class="batch-meta">
                <span><b>{{ batch.roast_count }}</b><small>已烘锅数</small></span>
                <span><b>{{ number(batch.remaining_green_weight_g, ' g') }}</b><small>剩余生豆</small></span>
                <span><b>{{ display(batch.latest_roast_date) }}</b><small>最近一锅</small></span>
                <span><b>{{ number(batch.latest_dtr_pct, '%') }}</b><small>最近 DTR</small></span>
                <span><b>{{ batch.latest_cupping_score ? batch.latest_cupping_score + '/5' : '未杯测' }}</b><small>最近评分</small></span>
              </div>
              <div class="actions">
                <a role="button" class="secondary" :href="'/beans/' + batch.id">进入批次</a>
                <a role="button" class="primary" :href="'/beans/' + batch.id + '/roasts/new'">新增本批次烘焙</a>
              </div>
            </article>
          </div>
        </section>

        <dialog ref="beanBatchDialog" class="form-dialog">
          <article>
            <header>
              <button aria-label="关闭" rel="prev" type="button" @click="closeBeanBatchDialog"></button>
              <h2>新增生豆批次</h2>
            </header>
            <form @submit.prevent="createBeanBatch">
              <div class="form-grid">
                <label>豆子名称<input v-model="newBeanBatch.name" required placeholder="例如 26 · 埃塞 · ALO · 74158"></label>
                <label>产地 / 庄园<input v-model="newBeanBatch.origin"></label>
                <label>处理法<input v-model="newBeanBatch.process"></label>
                <label>品种<input v-model="newBeanBatch.variety"></label>
                <label>购入生豆重量（g）<input v-model="newBeanBatch.purchase_weight_g" type="number" min="0" step="0.1"></label>
                <label>剩余生豆重量（g）<input v-model="newBeanBatch.remaining_green_weight_g" type="number" min="0" step="0.1"></label>
                <label class="full">备注<textarea v-model="newBeanBatch.notes"></textarea></label>
              </div>
              <footer class="actions">
                <button type="submit">创建批次</button>
                <button type="button" class="secondary" @click="closeBeanBatchDialog">取消</button>
                <span class="message">{{ roastMessage }}</span>
              </footer>
            </form>
          </article>
        </dialog>
      </section>

      <section v-else-if="view === 'bean-batch-detail'">
        <section class="panel">
          <div class="panel-heading">
            <div>
              <h2>{{ beanBatchDetail?.name || '生豆批次' }}</h2>
              <p v-if="beanBatchDetail">{{ display(beanBatchDetail.origin) }} · {{ display(beanBatchDetail.process) }} · {{ display(beanBatchDetail.variety) }}</p>
            </div>
            <div class="heading-actions">
              <a role="button" class="primary" :href="'/beans/' + routeBeanBatchId + '/roasts/new'">新增本批次烘焙</a>
              <a role="button" class="secondary" href="/roasts">返回批次列表</a>
            </div>
          </div>
          <p class="message">{{ roastMessage }}</p>

          <div v-if="!beanBatchDetail" class="empty">正在加载生豆批次</div>
          <div v-else>
            <div class="info-grid compact-info">
              <div class="tag"><span class="muted">剩余生豆</span><span>{{ number(beanBatchDetail.remaining_green_weight_g, ' g') }}</span></div>
              <div class="tag"><span class="muted">购入重量</span><span>{{ number(beanBatchDetail.purchase_weight_g, ' g') }}</span></div>
              <div class="tag"><span class="muted">已烘锅数</span><span>{{ beanBatchDetail.roast_count }} 锅</span></div>
              <div class="tag full"><span class="muted">备注</span><span>{{ display(beanBatchDetail.notes) }}</span></div>
            </div>

            <section class="section">
              <h3>本批次烘焙记录</h3>
              <div v-if="!currentBatchRoasts.length" class="empty">这批豆子还没有烘焙记录。</div>
              <div v-else class="list">
                <details v-for="roast in currentBatchRoasts" :key="roast.id" class="record">
                  <summary class="summary-row roast-summary-row">
                    <strong>{{ roast.roast_date }}</strong>
                    <span><span class="muted">投豆量</span><span class="value">{{ number(roast.batch_weight_g, ' g') }}</span></span>
                    <span><span class="muted">熟豆重</span><span class="value">{{ number(roast.roasted_weight_g, ' g') }}</span></span>
                    <span><span class="muted">失重率</span><span class="value">{{ number(roast.weight_loss_pct, '%') }}</span></span>
                    <span><span class="muted">黄点</span><span class="value">{{ formatSeconds(roast.actual_yellow_time_s) }}</span></span>
                    <span><span class="muted">一爆</span><span class="value">{{ formatSeconds(roast.actual_first_crack_time_s) }}</span></span>
                    <span><span class="muted">下豆</span><span class="value">{{ formatSeconds(roast.actual_drop_time_s) }}</span></span>
                    <span><span class="muted">发展</span><span class="value">{{ formatSeconds(roast.development_time_sec) }}</span></span>
                    <span><span class="muted">DTR</span><span class="value">{{ number(roast.dtr_pct, '%') }}</span></span>
                    <span><span class="muted">评分</span><span class="value">{{ roast.cupping_score ? roast.cupping_score + '/5' : roastScore(roast) }}</span></span>
                    <a role="button" class="secondary quick-cupping-button" :href="'/roasts/' + roast.id + '/cupping'" @click.stop>新增杯测</a>
                    <label class="compare-check" @click.stop>
                      <input type="checkbox" :checked="batchCompareIds.includes(String(roast.id))" @change="toggleBatchCompare(roast.id, $event)">
                      对比
                    </label>
                  </summary>

                  <div class="section info-grid">
                    <div class="tag full">
                      <span class="muted">杯测记录</span>
                      <span v-if="!roast.cuppings?.length">还没有杯测，点击摘要行的“新增杯测”快速添加</span>
                      <span v-else>
                        <span v-for="cupping in roast.cuppings" :key="cupping.id" class="inline-cupping">
                          {{ cupping.cupping_date }} · {{ display(cupping.rest_hours) }} 小时 · {{ display(cupping.overall) }}/5：
                          {{ display(cupping.flavor_notes || cupping.conclusion) }}
                        </span>
                      </span>
                    </div>
                    <div class="tag full"><span class="muted">这一锅标题</span><span>{{ display(roast.roast_label) }}</span></div>
                    <div class="tag full"><span class="muted">事前设计曲线</span><span>黄点 {{ formatSeconds(roast.plan_yellow_time_s) }} / {{ number(roast.plan_yellow_temp_c, '℃') }}；一爆 {{ formatSeconds(roast.plan_first_crack_time_s) }} / {{ number(roast.plan_first_crack_temp_c, '℃') }}；下豆 {{ formatSeconds(roast.plan_drop_time_s) }} / {{ number(roast.plan_drop_temp_c, '℃') }}</span></div>
                    <div class="tag full"><span class="muted">设计意图</span><span>{{ display(roast.plan_note) }}</span></div>
                    <div class="tag full"><span class="muted">事中实际跟踪</span><span>黄点 {{ formatSeconds(roast.actual_yellow_time_s) }}；一爆 / 梅纳结束 {{ formatSeconds(roast.actual_first_crack_time_s) }}；下豆 {{ formatSeconds(roast.actual_drop_time_s) }}</span></div>
                    <div class="tag full"><span class="muted">火力 / 风门 / 观察记录</span><span>{{ display(roast.control_log) }}</span></div>
                    <div class="tag full"><span class="muted">当锅观察</span><span>{{ display(roast.roast_notes) }}</span></div>
                    <div class="tag"><span class="muted">缺陷</span><span>{{ display(roast.defects || roast.latest_cupping?.defect_notes) }}</span></div>
                    <div class="tag full"><span class="muted">下一锅调整思路</span><span>{{ display(roast.next_adjustment || roast.latest_cupping?.next_roast_adjustment) }}</span></div>
                  </div>

                  <div class="section actions">
                    <a role="button" class="secondary" :href="'/roasts/' + roast.id + '/edit'">编辑这锅</a>
                    <a role="button" class="secondary" :href="'/roasts/' + roast.id">查看旧详情</a>
                  </div>
                </details>
              </div>
            </section>

            <section class="section">
              <h3>对比本批次烘焙</h3>
              <div v-if="selectedBatchRoasts.length < 2" class="empty">勾选 2-4 锅后展示对比。</div>
              <div v-else class="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>指标</th>
                      <th v-for="roast in selectedBatchRoasts" :key="roast.id">{{ roast.roast_date }}<br>{{ display(roast.roast_label) }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr><td>投豆量</td><td v-for="roast in selectedBatchRoasts" :key="'batch-' + roast.id">{{ number(roast.batch_weight_g, ' g') }}</td></tr>
                    <tr><td>失重率</td><td v-for="roast in selectedBatchRoasts" :key="'loss-' + roast.id">{{ number(roast.weight_loss_pct, '%') }}</td></tr>
                    <tr><td>黄点</td><td v-for="roast in selectedBatchRoasts" :key="'yellow-' + roast.id">{{ formatSeconds(roast.actual_yellow_time_s) }}</td></tr>
                    <tr><td>一爆</td><td v-for="roast in selectedBatchRoasts" :key="'fc-' + roast.id">{{ formatSeconds(roast.actual_first_crack_time_s) }}</td></tr>
                    <tr><td>下豆</td><td v-for="roast in selectedBatchRoasts" :key="'drop-' + roast.id">{{ formatSeconds(roast.actual_drop_time_s) }}</td></tr>
                    <tr><td>发展时间</td><td v-for="roast in selectedBatchRoasts" :key="'dev-' + roast.id">{{ formatSeconds(roast.development_time_sec) }}</td></tr>
                    <tr><td>DTR</td><td v-for="roast in selectedBatchRoasts" :key="'dtr-' + roast.id">{{ number(roast.dtr_pct, '%') }}</td></tr>
                    <tr><td>杯测评分</td><td v-for="roast in selectedBatchRoasts" :key="'score-' + roast.id">{{ roast.cupping_score ? roast.cupping_score + '/5' : roastScore(roast) }}</td></tr>
                    <tr><td>缺陷</td><td v-for="roast in selectedBatchRoasts" :key="'defects-' + roast.id">{{ display(roast.defects || roast.latest_cupping?.defect_notes) }}</td></tr>
                    <tr><td>下一锅调整</td><td v-for="roast in selectedBatchRoasts" :key="'next-' + roast.id">{{ display(roast.next_adjustment || roast.latest_cupping?.next_roast_adjustment) }}</td></tr>
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        </section>
      </section>

      <section v-else-if="['bean-roast-new', 'roast-new', 'roast-edit'].includes(view)">
        <section class="panel">
          <div class="panel-heading">
            <div>
              <h2>{{ roastFormTitle }}</h2>
              <p>选择生豆会自动快照豆子信息；保存时会扣减生豆库存。</p>
            </div>
            <a role="button" class="secondary" href="/roasts">返回列表</a>
          </div>

          <form @submit.prevent="submitRoast">
            <section v-if="view === 'roast-edit'" class="section">
              <h3>关联生豆批次</h3>
              <div class="form-grid">
                <label>
                  选择生豆批次
                  <select v-model="roastForm.bean_batch_id" @change="applyGreenSnapshot">
                    <option value="">不关联生豆，手动填写</option>
                    <option v-for="bean in availableGreenBeansForRoast" :key="bean.id" :value="String(bean.id)">
                      {{ bean.display_name }} · {{ bean.total_weight }} g
                    </option>
                  </select>
                </label>
                <label>豆子名称<input v-model="roastForm.bean_name_snapshot" required></label>
                <label>产地 / 庄园<input v-model="roastForm.bean_origin"></label>
                <label>处理法<input v-model="roastForm.bean_process"></label>
              </div>
            </section>

            <section v-else-if="beanBatchDetail" class="section batch-context">
              <h3>{{ beanBatchDetail.name }}</h3>
              <p>{{ display(beanBatchDetail.origin) }} · {{ display(beanBatchDetail.process) }} · {{ display(beanBatchDetail.variety) }}</p>
            </section>

            <section class="section stage-card">
              <h3>1. 事前设计曲线</h3>
              <div class="form-grid">
                <label>烘焙日期<input v-model="roastForm.roast_date" type="date" required></label>
                <label>烘豆机<input v-model="roastForm.roaster_model"></label>
                <label>这一锅短标题<input v-model="roastForm.roast_label" placeholder="例如 第6锅 / 降低发展测试"></label>
                <label>投豆量（g）<input v-model="roastForm.batch_weight_g" type="number" min="0" step="0.1" required></label>
                <label>计划黄点时间<input v-model="roastForm.plan_yellow_time_s" placeholder="3:20"></label>
                <label>计划黄点温度（℃）<input v-model="roastForm.plan_yellow_temp_c" type="number" min="0" step="0.1"></label>
                <label>计划一爆时间<input v-model="roastForm.plan_first_crack_time_s" placeholder="4:00"></label>
                <label>计划一爆温度（℃）<input v-model="roastForm.plan_first_crack_temp_c" type="number" min="0" step="0.1"></label>
                <label>计划下豆时间<input v-model="roastForm.plan_drop_time_s" placeholder="4:50"></label>
                <label>计划下豆温度（℃）<input v-model="roastForm.plan_drop_temp_c" type="number" min="0" step="0.1"></label>
                <label class="full">设计意图<textarea v-model="roastForm.plan_note" placeholder="例如 降低发展，保留花果香"></textarea></label>
              </div>
            </section>

            <section class="section stage-card">
              <h3>2. 事中实际跟踪</h3>
              <div class="metric-strip">
                <span><b>{{ number(roastPreviewMetrics.weight_loss_pct, '%') }}</b><small>失重率</small></span>
                <span><b>{{ formatSeconds(roastPreviewMetrics.development_time_s) }}</b><small>发展时间</small></span>
                <span><b>{{ number(roastPreviewMetrics.dtr_pct, '%') }}</b><small>DTR</small></span>
                <span><b>{{ formatSeconds(roastPreviewMetrics.dehydration_duration_s) }}</b><small>脱水期</small></span>
                <span><b>{{ formatSeconds(roastPreviewMetrics.maillard_duration_s) }}</b><small>梅纳期</small></span>
              </div>
              <div class="form-grid">
                <label>熟豆重量（g）<input v-model="roastForm.roasted_weight_g" type="number" min="0" step="0.1"></label>
                <label>杯测预留（g）<input v-model="roastForm.cupping_reserved_g" type="number" min="0" step="0.01"></label>
                <label>实际黄点时间<input v-model="roastForm.actual_yellow_time_s" placeholder="3:30"></label>
                <label>实际黄点温度（℃）<input v-model="roastForm.actual_yellow_temp_c" type="number" min="0" step="0.1"></label>
                <label>实际一爆 / 梅纳结束时间<input v-model="roastForm.actual_first_crack_time_s" placeholder="4:05"></label>
                <label>实际一爆温度（℃）<input v-model="roastForm.actual_first_crack_temp_c" type="number" min="0" step="0.1"></label>
                <label>实际下豆时间<input v-model="roastForm.actual_drop_time_s" placeholder="4:53"></label>
                <label>实际下豆温度（℃）<input v-model="roastForm.actual_drop_temp_c" type="number" min="0" step="0.1"></label>
                <label class="full">火力 / 风门 / 观察记录<textarea v-model="roastForm.control_log" placeholder="0:00 火力25 风门50；1:30 转黄降火到22；3:50 一爆开始；4:53 下豆"></textarea></label>
                <label class="full">当锅观察备注<textarea v-model="roastForm.roast_notes" placeholder="例如 豆子流化正常，颜色略深"></textarea></label>
                <label class="check-line">
                  <input v-model="roastForm.create_roasted_batch" type="checkbox">
                  同时生成熟豆库存批次
                </label>
              </div>
            </section>

            <section class="section stage-card">
              <h3>3. 事后杯测反馈</h3>
              <div class="form-grid">
                <label>杯测日期<input v-model="roastForm.cupping_date" type="date"></label>
                <label>杯测评分（1-5）<input v-model="roastForm.cupping_score" type="number" min="1" max="5" step="1"></label>
                <label class="full">杯测描述<textarea v-model="roastForm.cupping_notes"></textarea></label>
                <label class="full">缺陷<textarea v-model="roastForm.defects" placeholder="发展偏长、焦苦、空洞、酸质发闷"></textarea></label>
                <label class="full">下一锅调整思路<textarea v-model="roastForm.next_adjustment" placeholder="发展从 60 秒压到 45 秒；一爆后提前降火"></textarea></label>
                <label class="full">心得<textarea v-model="roastForm.learning_note"></textarea></label>
              </div>
            </section>

            <footer class="actions">
              <button type="submit">{{ roastSubmitLabel }}</button>
              <a role="button" class="secondary" :href="routeBeanBatchId ? '/beans/' + routeBeanBatchId : '/roasts'">取消</a>
              <span class="message">{{ roastMessage }}</span>
            </footer>
          </form>
        </section>
      </section>

      <section v-else-if="view === 'roast-detail'">
        <section class="panel">
          <div class="panel-heading">
            <div>
              <h2>烘焙详情</h2>
              <p>原始记录、自动指标、杯测结果和库存联动流水。</p>
            </div>
            <div class="heading-actions">
              <a role="button" class="secondary" :href="'/roasts/' + routeRoastId + '/edit'">编辑烘焙</a>
              <a role="button" class="secondary" :href="'/roasts/' + routeRoastId + '/cupping'">添加杯测</a>
              <a role="button" class="secondary" href="/roasts">返回列表</a>
            </div>
          </div>
          <p class="message">{{ roastMessage }}</p>
          <div v-if="!roastDetail" class="empty">正在加载烘焙记录</div>
          <div v-else>
            <div class="info-grid">
              <div class="tag"><span class="muted">日期</span><span>{{ roastDetail.roast_date }}</span></div>
              <div class="tag"><span class="muted">豆子</span><span>{{ roastDetail.bean_name_snapshot }}</span></div>
              <div class="tag"><span class="muted">载量</span><span>{{ number(roastDetail.batch_weight_g, ' g') }}</span></div>
              <div class="tag"><span class="muted">熟豆重量</span><span>{{ number(roastDetail.roasted_weight_g, ' g') }}</span></div>
              <div class="tag"><span class="muted">失重率</span><span>{{ number(roastDetail.weight_loss_pct, '%') }}</span></div>
              <div class="tag"><span class="muted">发展时间</span><span>{{ formatSeconds(roastDetail.development_time_sec) }}</span></div>
              <div class="tag"><span class="muted">DTR</span><span>{{ number(roastDetail.dtr_pct, '%') }}</span></div>
              <div class="tag"><span class="muted">杯测总评</span><span>{{ roastScore(roastDetail) }}</span></div>
            </div>

            <section class="section">
              <h3>阶段指标</h3>
              <div class="info-grid">
                <div class="tag"><span class="muted">干燥段</span><span>{{ formatSeconds(roastDetail.drying_time_sec) }}</span></div>
                <div class="tag"><span class="muted">梅纳段</span><span>{{ formatSeconds(roastDetail.maillard_time_sec) }}</span></div>
                <div class="tag"><span class="muted">黄点到一爆</span><span>{{ formatSeconds(roastDetail.yellow_to_fc_sec) }}</span></div>
                <div class="tag"><span class="muted">一爆到下豆升温</span><span>{{ number(roastDetail.fc_to_drop_temp_rise_c, '℃') }}</span></div>
                <div class="tag"><span class="muted">可饮用重量</span><span>{{ number(roastDetail.drinkable_weight_g, ' g') }}</span></div>
                <div class="tag"><span class="muted">杯测预留</span><span>{{ number(roastDetail.cupping_reserved_g, ' g') }}</span></div>
              </div>
            </section>

            <section class="section">
              <h3>原始记录</h3>
              <div class="info-grid">
                <div class="tag"><span class="muted">烘豆机</span><span>{{ display(roastDetail.roaster_model) }}</span></div>
                <div class="tag"><span class="muted">方案</span><span>{{ display(roastDetail.profile_name) }}</span></div>
                <div class="tag"><span class="muted">起始火力 / 风门</span><span>{{ display(roastDetail.heat_start) }} / {{ display(roastDetail.fan_start) }}</span></div>
                <div class="tag"><span class="muted">黄点</span><span>{{ formatSeconds(roastDetail.yellow_time_sec) }} · {{ number(roastDetail.yellow_temp_c, '℃') }}</span></div>
                <div class="tag"><span class="muted">一爆</span><span>{{ formatSeconds(roastDetail.first_crack_time_sec) }} · {{ number(roastDetail.first_crack_temp_c, '℃') }}</span></div>
                <div class="tag"><span class="muted">下豆</span><span>{{ formatSeconds(roastDetail.drop_time_sec) }} · {{ number(roastDetail.drop_temp_c, '℃') }}</span></div>
                <div class="tag"><span class="muted">烘焙度</span><span>{{ roastLevelLabel(roastDetail.roast_level) }}</span></div>
                <div class="tag full"><span class="muted">操作计划</span><span>{{ display(roastDetail.operation_plan) }}</span></div>
                <div class="tag full"><span class="muted">总备注</span><span>{{ display(roastDetail.general_notes) }}</span></div>
                <div class="tag full"><span class="muted">心得</span><span>{{ display(roastDetail.learning_note) }}</span></div>
                <div class="tag full"><span class="muted">下一锅建议</span><span>{{ display(roastDetail.next_adjustment) }}</span></div>
              </div>
            </section>

            <section class="section">
              <h3>灵活事件</h3>
              <div v-if="!roastDetail.events.length" class="empty">没有额外事件</div>
              <div v-else class="table-wrap">
                <table>
                  <thead><tr><th>事件</th><th>时间</th><th>温度</th><th>火力</th><th>风门</th><th>备注</th></tr></thead>
                  <tbody>
                    <tr v-for="event in roastDetail.events" :key="event.id">
                      <td>{{ eventTypeLabel(event.event_type) }}</td>
                      <td>{{ formatSeconds(event.time_sec) }}</td>
                      <td>{{ number(event.temp_c, '℃') }}</td>
                      <td>{{ display(event.heat_setting) }}</td>
                      <td>{{ display(event.fan_setting) }}</td>
                      <td>{{ display(event.note) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>

            <section class="section">
              <h3>杯测记录</h3>
              <div v-if="!roastDetail.cuppings.length" class="empty">还没有杯测记录</div>
              <div v-for="cupping in roastDetail.cuppings" :key="cupping.id" class="cupping-card">
                <strong>{{ cupping.cupping_date }} · 总评 {{ display(cupping.overall) }}/5</strong>
                <p>{{ display(cupping.conclusion) }}</p>
                <small>{{ display(cupping.flavor_notes) }}</small>
              </div>
            </section>

            <section class="section">
              <h3>库存流水</h3>
              <div v-if="!roastDetail.transactions.length" class="empty">没有库存流水</div>
              <div v-else class="table-wrap">
                <table>
                  <thead><tr><th>类型</th><th>重量</th><th>备注</th><th>时间</th></tr></thead>
                  <tbody>
                    <tr v-for="transaction in roastDetail.transactions" :key="transaction.id">
                      <td>{{ transaction.transaction_type }}</td>
                      <td>{{ number(transaction.weight_g, ' g') }}</td>
                      <td>{{ display(transaction.note) }}</td>
                      <td>{{ transaction.created_at }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        </section>
      </section>

      <section v-else-if="view === 'roast-cupping'">
        <section class="panel">
          <div class="panel-heading">
            <div>
              <h2>添加杯测记录</h2>
              <p v-if="roastDetail">{{ roastDetail.bean_name_snapshot }} · {{ roastDetail.roast_date }}。同一锅可以按 12 小时、48 小时等多次记录。</p>
            </div>
            <a role="button" class="secondary" :href="roastDetail?.bean_batch_id ? '/beans/' + roastDetail.bean_batch_id : '/roasts/' + routeRoastId">返回</a>
          </div>

          <form @submit.prevent="createCupping">
            <div class="form-grid">
              <label>杯测日期<input v-model="newCupping.cupping_date" type="date" required></label>
              <label>养豆时间（小时）<input v-model="newCupping.rest_hours" type="number" min="0" step="0.1" placeholder="12 或 48"></label>
              <label>粉量（g）<input v-model="newCupping.dose_g" type="number" min="0" step="0.01"></label>
              <label>水量（ml）<input v-model="newCupping.water_ml" type="number" min="0" step="1"></label>
              <label>水温（℃）<input v-model="newCupping.water_temp_c" type="number" min="0" step="0.1"></label>
              <label>研磨度<input v-model="newCupping.grind_setting"></label>
              <label>磨豆机<input v-model="newCupping.grinder"></label>
            </div>

            <section class="section">
              <h3>评分（1-5）</h3>
              <div class="score-grid">
                <label v-for="field in cuppingScoreFields" :key="field[0]">
                  {{ field[1] }}
                  <input v-model="newCupping[field[0]]" type="number" min="1" max="5" step="1">
                </label>
              </div>
            </section>

            <section class="section">
              <div class="form-grid">
                <label class="full">风味描述<textarea v-model="newCupping.flavor_notes"></textarea></label>
                <label class="full">缺陷记录<textarea v-model="newCupping.defect_notes"></textarea></label>
                <label class="full">结论<textarea v-model="newCupping.conclusion"></textarea></label>
                <label class="full">下一锅调整建议<textarea v-model="newCupping.next_roast_adjustment"></textarea></label>
              </div>
            </section>

            <footer class="actions">
              <button type="submit">保存杯测</button>
              <a role="button" class="secondary" :href="roastDetail?.bean_batch_id ? '/beans/' + roastDetail.bean_batch_id : '/roasts/' + routeRoastId">取消</a>
              <span class="message">{{ cuppingMessage }}</span>
            </footer>
          </form>
        </section>
      </section>

      <section v-else-if="view === 'roast-compare'">
        <section class="panel">
          <div class="panel-heading">
            <div>
              <h2>烘焙对比</h2>
              <p>选择 2-4 锅，对比关键指标和杯测结果。</p>
            </div>
            <a role="button" class="secondary" href="/roasts">返回列表</a>
          </div>
          <p class="message">{{ roastMessage }}</p>

          <div class="compare-picker">
            <label v-for="roast in roasts" :key="roast.id">
              <input type="checkbox" :checked="compareIds.includes(String(roast.id))" @change="toggleCompare(roast.id, $event)">
              {{ roast.roast_date }} · {{ roast.bean_name_snapshot }}
            </label>
          </div>

          <div v-if="selectedRoasts.length < 2" class="empty">至少选择 2 锅开始对比</div>
          <div v-else class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>指标</th>
                  <th v-for="roast in selectedRoasts" :key="roast.id">
                    <a :href="'/roasts/' + roast.id">{{ roast.roast_date }}<br>{{ roast.bean_name_snapshot }}</a>
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr><td>载量</td><td v-for="roast in selectedRoasts" :key="'load-' + roast.id">{{ number(roast.batch_weight_g, ' g') }}</td></tr>
                <tr><td>熟豆重量</td><td v-for="roast in selectedRoasts" :key="'roasted-' + roast.id">{{ number(roast.roasted_weight_g, ' g') }}</td></tr>
                <tr><td>失重率</td><td v-for="roast in selectedRoasts" :key="'loss-' + roast.id">{{ number(roast.weight_loss_pct, '%') }}</td></tr>
                <tr><td>黄点</td><td v-for="roast in selectedRoasts" :key="'yellow-' + roast.id">{{ formatSeconds(roast.yellow_time_sec) }}</td></tr>
                <tr><td>一爆</td><td v-for="roast in selectedRoasts" :key="'fc-' + roast.id">{{ formatSeconds(roast.first_crack_time_sec) }}</td></tr>
                <tr><td>下豆</td><td v-for="roast in selectedRoasts" :key="'drop-' + roast.id">{{ formatSeconds(roast.drop_time_sec) }}</td></tr>
                <tr><td>发展时间</td><td v-for="roast in selectedRoasts" :key="'dev-' + roast.id">{{ formatSeconds(roast.development_time_sec) }}</td></tr>
                <tr><td>DTR</td><td v-for="roast in selectedRoasts" :key="'dtr-' + roast.id">{{ number(roast.dtr_pct, '%') }}</td></tr>
                <tr><td>杯测总评</td><td v-for="roast in selectedRoasts" :key="'score-' + roast.id">{{ roastScore(roast) }}</td></tr>
                <tr><td>杯测结论</td><td v-for="roast in selectedRoasts" :key="'conclusion-' + roast.id">{{ display(roast.latest_cupping?.conclusion) }}</td></tr>
              </tbody>
            </table>
          </div>
        </section>
      </section>

      <section v-else-if="view === 'brews'">
        <section class="panel">
          <div class="panel-heading">
            <div>
              <h2>冲煮记录</h2>
              <p>点击新增按钮后填写本次冲煮日志。</p>
            </div>
            <div class="heading-actions">
              <button type="button" class="secondary" @click="exportAllBrews" :disabled="!brews.length">导出全部</button>
              <button type="button" class="primary" @click="openBrewDialog">新增冲煮记录</button>
            </div>
          </div>
          <p class="message">{{ brewMessage }}</p>
          <div v-if="!brews.length" class="empty">还没有冲煮记录</div>

          <div class="list">
            <details v-for="brew in brews" :key="brew.id" :id="'brew-' + brew.id" :open="initialBrewAnchor === '#brew-' + brew.id" class="record">
              <summary class="summary-row brew-summary-row">
                <strong>{{ brew.brew_date }}</strong>
                <span><span class="muted">咖啡</span><a class="value" :href="'/?bean=' + brew.bean_id">{{ brew.bean.name }}</a></span>
                <span><span class="muted">水质</span><span class="value">{{ display(brew.data.technique.water_type) }}</span></span>
                <span><span class="muted">水温</span><span class="value">{{ display(brew.data.technique.water_temperature) }}</span></span>
                <span><span class="muted">研磨</span><span class="value">{{ display(brew.data.technique.grind_size) }}</span></span>
                <span><span class="muted">比例</span><span class="value">{{ display(brew.data.technique.ratio) }}</span></span>
                <span><span class="muted">评分</span><span class="value">{{ display(brew.data.tasting.score) }}</span></span>
                <button type="button" class="secondary export-button" @click="exportBrewFromSummary($event, brew)">导出</button>
              </summary>

              <a :href="'/tastings?cup=brew-' + brew.id">为这杯写个人口味反馈</a>
              <form class="section" @submit.prevent="updateBrew(brew)">
                <label>
                  咖啡豆
                  <select v-model="brewDrafts[brew.id].bean_id" required>
                    <option v-for="bean in inventory.items" :key="bean.id" :value="String(bean.id)">
                      {{ bean.name }} · {{ bean.roaster }}
                    </option>
                  </select>
                </label>

                <div class="form-grid section">
                  <field-input :field="['brew_date', '冲煮日期', 'date', true]" :model="brewDrafts[brew.id]"></field-input>
                  <field-input :field="['roast_degree', '烘焙度（自评0-10）']" :model="brewDrafts[brew.id].data.bean_context"></field-input>
                  <field-input :field="['warming_time', '回温时间']" :model="brewDrafts[brew.id].data.bean_context"></field-input>
                </div>

                <brew-fields :data="brewDrafts[brew.id].data"></brew-fields>
                <div class="actions">
                  <button>保存修改</button>
                  <button type="button" class="secondary danger" @click="deleteBrew(brew)">删除</button>
                  <span class="message">{{ rowMessage['brew-' + brew.id] }}</span>
                </div>
              </form>
            </details>
          </div>
        </section>

        <dialog ref="brewDialog" class="form-dialog">
          <article>
            <header>
              <button aria-label="关闭" rel="prev" type="button" @click="closeBrewDialog"></button>
              <h2>新增冲煮记录</h2>
            </header>

            <form @submit.prevent="createBrew">
              <label>
                咖啡豆
                <select v-model="newBrew.bean_id" required>
                  <option value="">选择一支咖啡豆</option>
                  <option v-for="bean in inventory.items" :key="bean.id" :value="String(bean.id)">
                    {{ bean.name }} · {{ bean.roaster }}
                  </option>
                </select>
              </label>

              <div class="form-grid section">
                <field-input :field="['brew_date', '冲煮日期', 'date', true]" :model="newBrew"></field-input>
                <field-input :field="['roast_degree', '烘焙度（自评0-10）']" :model="newBrew.data.bean_context"></field-input>
                <field-input :field="['warming_time', '回温时间']" :model="newBrew.data.bean_context"></field-input>
              </div>

              <brew-fields :data="newBrew.data"></brew-fields>

              <footer class="actions">
                <button type="submit">保存冲煮记录</button>
                <button type="button" class="secondary" @click="closeBrewDialog">取消</button>
                <span class="message">{{ brewMessage }}</span>
              </footer>
            </form>
          </article>
        </dialog>
      </section>
      </div>
    </main>
  `,
}).mount("#app");
