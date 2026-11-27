// Shared cups, one independently editable note per taster and cup.
const TastingRoom = {
  data() {
    return {
      people: [], cups: [], notes: [], inventory: [], personId: "", cupId: "", name: "",
      beanId: "", mode: "inventory", brewDate: "", creatingUnconfirmed: false,
      scores: { overall: "整体", sweetness: "甜感", acidity: "酸质", aroma: "香气" },
      draft: {}, original: "{}", revision: 0, busy: false, message: "", error: "",
    };
  },
  computed: {
    person() { return this.people.find(p => p.id === this.personId); },
    cup() { return this.cups.find(c => c.id === this.cupId); },
    visibleCups() {
      return this.mode === "history" ? this.cups : this.cups.filter(c => c.bean_id === this.beanId);
    },
    history() {
      return this.notes.filter(n => n.person_id === this.personId)
        .map(n => ({ ...n, source: this.cups.find(c => c.id === n.cup) }))
        .sort((a, b) => (b.source?.date || "").localeCompare(a.source?.date || ""));
    },
  },
  async mounted() {
    this.busy = true;
    try {
      const data = await api("/api/tastings");
      Object.assign(this, data);
      let saved;
      try { saved = JSON.parse(localStorage.getItem("coffee-tasting-selection")); } catch {}
      this.personId = this.people.find(p => p.id === saved?.person)?.id || "";
      const savedCup = this.cups.find(c => c.id === saved?.cup);
      const target = new URLSearchParams(location.search).get("cup") ||
        (this.inventory.some(b => b.id === savedCup?.bean_id) ? savedCup.id : "");
      this.cupId = this.cups.find(c => c.id === target)?.id || "";
      const selected = this.cups.find(c => c.id === this.cupId);
      if (selected && this.inventory.some(b => b.id === selected.bean_id)) this.beanId = selected.bean_id;
      else if (selected) this.mode = "history";
      const today = new Date();
      this.brewDate = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
      this.readDraft();
    } catch (err) { this.error = err.message; }
    finally { this.busy = false; }
  },
  methods: {
    readDraft() {
      const note = this.notes.find(n => n.person_id === this.personId && n.cup === this.cupId);
      this.draft = { ...note?.feedback };
      this.original = JSON.stringify(this.draft);
      this.revision = note?.revision || 0;
      try { localStorage.setItem("coffee-tasting-selection", JSON.stringify({ person: this.personId, cup: this.cupId })); } catch {}
    },
    canLeave() {
      return this.original === JSON.stringify(this.draft) || confirm("放弃当前未保存的评价？");
    },
    switchTo(person, cup, event) {
      if (!this.canLeave()) {
        if (event) event.target.value = event.target.name === "person" ? this.personId : this.cupId;
        return;
      }
      this.personId = person;
      this.cupId = cup;
      const chosen = this.cups.find(c => c.id === cup);
      if (chosen) {
        if (this.inventory.some(b => b.id === chosen.bean_id)) {
          this.mode = "inventory";
          this.beanId = chosen.bean_id;
        } else this.mode = "history";
      }
      this.message = this.error = "";
      this.readDraft();
    },
    selectBean(event) {
      if (!this.canLeave()) { event.target.value = this.beanId; return; }
      this.beanId = Number(event.target.value);
      this.cupId = "";
      this.message = this.error = "";
      this.readDraft();
    },
    selectMode(event) {
      if (!this.canLeave()) { event.target.value = this.mode; return; }
      this.mode = event.target.value;
      this.cupId = "";
      this.readDraft();
    },
    async createCup() {
      if (this.busy || !this.beanId || this.creatingUnconfirmed || !this.canLeave()) return;
      this.busy = true;
      this.message = this.error = "";
      try {
        const response = await fetch("/api/brews", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ bean_id: this.beanId, brew_date: this.brewDate, data: {} }),
          signal: AbortSignal.timeout(10000),
        });
        const result = await response.json();
        if (!response.ok) throw Object.assign(new Error(result.error || "保存失败"), { confirmedFailure: true });
        const brew = result.item;
        this.cups.unshift({ id: "brew-" + brew.id, bean_id: brew.bean_id, date: brew.brew_date, name: brew.bean.name });
        this.cupId = "brew-" + brew.id;
        this.readDraft();
        this.message = "已建立本杯记录，可以填写反馈";
      } catch (err) {
        this.creatingUnconfirmed = !err.confirmedFailure;
        this.error = this.creatingUnconfirmed ? "保存结果未确认，请刷新核对本杯是否已建立，再继续记录。" : err.message;
      } finally { this.busy = false; }
    },
    async createPerson() {
      if (this.busy || !this.canLeave()) return;
      this.busy = true;
      this.message = this.error = "";
      try {
        const person = await api("/api/tastings/people", { method: "POST", body: JSON.stringify({ name: this.name }) });
        this.people.push(person);
        this.name = "";
        this.personId = person.id;
        this.readDraft();
        this.message = "已建立个人记录区";
      } catch (err) { this.error = err.message; } finally { this.busy = false; }
    },
    async save() {
      if (this.busy) return;
      this.busy = true;
      this.message = this.error = "";
      try {
        const feedback = Object.fromEntries(Object.entries(this.draft).filter(([,v]) => v !== "" && v != null));
        const item = { person_id: this.personId, cup: this.cupId, feedback, revision: this.revision };
        const result = await api("/api/tastings/feedback", { method: "POST", body: JSON.stringify(item) });
        item.revision = result.revision;
        this.notes = [item, ...this.notes.filter(n => n.person_id !== item.person_id || n.cup !== item.cup)];
        this.readDraft();
        this.message = "已保存到" + this.person.name + "的记录区";
      } catch (err) { this.error = err.message; } finally { this.busy = false; }
    },
    label(cup) { return cup.archive ? cup.name : cup.date + " · " + cup.name + " · #" + cup.id.slice(5); },
  },
  template: `
    <section class="tasting-room">
      <div class="panel-heading"><div><h1>个人品饮</h1><p>选一杯冲煮，用自己的名字记下喝到的味道。</p></div><a href="/brews">冲煮记录</a></div>
      <fieldset :disabled="busy">
        <article class="panel tasting-people">
          <label>当前品饮者<select name="person" :value="personId" @change="switchTo(Number($event.target.value), cupId, $event)">
            <option value="" disabled>选择个人记录区</option><option v-for="p in people" :key="p.id" :value="p.id">{{p.name}}</option>
          </select></label>
          <form @submit.prevent="createPerson"><label>新建品饮者<input v-model.trim="name" maxlength="40" placeholder="姓名或昵称" required></label><button type="submit" class="secondary">建立记录区</button></form>
        </article>
        <div v-if="person" class="tasting-columns">
          <article class="panel"><h2>{{person.name}}的口味反馈</h2>
            <label>记录来源<select :value="mode" @change="selectMode"><option value="inventory">从当前库存选豆</option><option value="history">查看历史冲煮</option></select></label>
            <template v-if="mode === 'inventory'">
              <label>当前库存咖啡豆<select :value="beanId" @change="selectBean">
                <option value="" disabled>选择这次喝的豆子</option>
                <option v-for="b in inventory" :key="b.id" :value="b.id">{{b.name}} · {{b.net_weight == null ? '重量待补' : b.net_weight + ' g'}} · #{{b.id}}</option>
              </select></label>
              <form v-if="beanId" @submit.prevent="createCup" class="section">
                <label>冲煮日期<input type="date" v-model="brewDate" required></label>
                <button type="submit" class="secondary" :disabled="creatingUnconfirmed">为这支豆新建一杯记录</button>
                <small>同一杯由多人品饮时，请选择下方已有记录。</small>
              </form>
            </template>
            <label v-if="mode === 'history' || beanId">已记录的冲煮<select name="cup" :value="cupId" @change="switchTo(personId,$event.target.value,$event)">
              <option value="" disabled>选择要评价的这一杯</option>
              <option v-for="c in visibleCups" :key="c.id" :value="c.id">{{label(c)}}</option></select></label>
            <p v-if="mode === 'inventory' && beanId && !visibleCups.length">这支豆还没有冲煮记录。已喝过的话，可以在上方记一杯。</p>
            <p v-if="!cup">选择一杯后填写口味反馈。</p>
            <form v-else @submit.prevent="save">
              <a :href="cup.archive ? '/api/tastings/source/' + cup.id : '/brews#' + cup.id" target="_blank" rel="noopener">查看这杯的原始记录 ↗</a>
              <h3>评分 <small>0–10，可留空</small></h3>
              <div class="tasting-scores"><label v-for="(title,key) in scores" :key="key">{{title}}<input v-model.number="draft[key]" type="number" min="0" max="10" step="any" placeholder="—"></label></div>
              <label>喝起来怎么样<textarea maxlength="2000" v-model="draft.taste" placeholder="例如，甜感好，尾段略涩"></textarea></label>
              <label>下次想怎么调<textarea maxlength="2000" v-model="draft.next" placeholder="选填"></textarea></label>
              <button type="submit">{{revision ? "保存修改" : "保存反馈"}}</button>
            </form>
          </article>
          <article class="panel"><h2>{{person.name}}的历史记录</h2>
            <p v-if="!history.length">第一条反馈会出现在这里。</p>
            <section v-for="n in history" :key="n.cup" class="tasting-note">
              <strong>{{n.source ? label(n.source) : n.cup}}</strong>
              <div class="tasting-marks"><span v-for="(title,k) in scores" :key="k"><template v-if="n.feedback[k] != null">{{title}} {{n.feedback[k]}}</template></span></div>
              <p v-if="n.feedback.taste">{{n.feedback.taste}}</p><p v-if="n.feedback.next">下次：{{n.feedback.next}}</p>
              <button class="secondary" type="button" @click="switchTo(personId,n.cup)">查看或修改</button>
            </section>
          </article>
        </div>
      </fieldset>
      <p v-if="error" role="alert" class="xb-error">{{error}}</p><p v-if="message" role="status">{{message}}</p>
    </section>`,
};
