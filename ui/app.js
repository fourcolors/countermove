const FIXTURE_PATH = "../contracts/fixtures";

const fixtureFiles = {
  company: "company.json",
  move: "move.json",
  pendingAction: "pending_action.json",
  personas: "persona_cards.json",
  recommendation: "recommendation.json",
  scoreResult: "score_result.json",
  traceEvents: "trace_events.json",
  tree: "tree.json",
  jargon: "../jargon.json",
};

const state = {
  advanced: false,
  selectedLeafId: null,
  data: null,
};

const humanize = (value) => ({
  smb: "Small businesses",
  mid: "Mid-sized businesses",
  undercut: "Offer a lower price",
  match: "Match your price",
  ignore: "Keep their price",
  raise: "Raise their price",
  hold: "Keep current price",
  partial_rollback: "Move partway back",
  annual_discount: "Offer an annual discount",
}[value] || value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()));

const money = (value) => new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: Number.isInteger(value) ? 0 : 2,
}).format(value);

function signedPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  const number = Number(value);
  const sign = number > 0 ? "+" : number < 0 ? "−" : "";
  return `${sign}${Math.abs(number)}%`;
}

function signedPercentValue(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  const number = Number(value);
  const sign = number > 0 ? "+" : number < 0 ? "−" : "";
  return `${sign}${Math.abs(number)}`;
}

function scoreSentence(score, jargon) {
  const values = {
    mid_pct: signedPercentValue(score.mid_pct),
    low_pct: signedPercentValue(score.low_pct),
    high_pct: signedPercentValue(score.high_pct),
  };
  const band = jargon.score_band.format.replace(/\{(mid_pct|low_pct|high_pct)\}/g, (_token, key) => values[key]);
  return `${jargon.score_band.plain}: ${band}`;
}

function priceSensitivity(mid, elasticity) {
  const [low, medium, high] = Object.keys(elasticity.levels);
  if (mid > elasticity.thresholds.medium_min) return low;
  if (mid < elasticity.thresholds.high_max) return high;
  return medium;
}

function competitorAttention(value, crossElasticity) {
  const [little, some, lot] = Object.keys(crossElasticity.levels);
  if (value >= crossElasticity.thresholds.a_lot_min) return lot;
  if (value >= crossElasticity.thresholds.some_min) return some;
  return little;
}

function pathDescription(pathId) {
  const match = pathId.match(/^leaf-(rival-[abc])-(undercut|match|ignore|raise)-(hold|partial_rollback|annual_discount)$/);
  if (!match) return humanize(pathId);
  const competitor = match[1].replace("rival-", "Rival ").toUpperCase().replace("RIVAL", "Rival");
  return `${humanize(match[3])} if ${competitor} chooses to ${humanize(match[2]).toLowerCase()}`;
}

function el(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function fixtureDomId(...parts) {
  return parts.join("-").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}

function advancedDetail(label, value) {
  const row = el("div", "advanced-only raw-row");
  row.append(el("span", "raw-name", label), el("code", "raw-value", value));
  return row;
}

function createMessage(copy, modifier = "") {
  const message = document.querySelector("#message-template").content.firstElementChild.cloneNode(true);
  if (modifier) message.classList.add(modifier);
  message.querySelector(".message-content").append(el("p", "message-copy", copy));
  document.querySelector("#conversation-feed").append(message);
  return message.querySelector(".message-content");
}

function renderUserMessage(move) {
  const article = el("article", "message message-user");
  const content = el("div", "message-content");
  content.append(el("p", "message-copy", `Show me what could happen if we raise ${humanize(move.plan)} from ${money(move.from)} to ${money(move.to)}.`));
  article.append(content, el("div", "avatar avatar-user", "You"));
  document.querySelector("#conversation-feed").append(article);
}

function renderWebsiteMessage(company) {
  const website = `https://${fixtureDomId(company.name)}.example`;
  const article = el("article", "message message-user");
  const content = el("div", "message-content");
  content.append(el("p", "message-copy", website));
  article.append(content, el("div", "avatar avatar-user", "You"));
  document.querySelector("#conversation-feed").append(article);
}

function renderCompany(company, jargon) {
  const content = createMessage(`I found ${company.name}. Here’s the business picture I used. You can review each field before we act.`);
  const card = el("section", "company-card widget");
  card.setAttribute("aria-labelledby", "company-title");

  const heading = el("div", "widget-heading");
  const titleWrap = el("div");
  titleWrap.append(el("span", "widget-label", "Company summary"), el("h2", "widget-title", company.name));
  titleWrap.querySelector("h2").id = "company-title";
  const editHint = el("span", "edit-hint", "Review fields");
  heading.append(titleWrap, editHint);
  card.append(heading);

  company.plans.forEach((plan) => {
    const planRow = el("div", "plan-row");
    const planName = el("label", "field-group");
    const planNameId = fixtureDomId(company.name, plan.id, "plan-name");
    planName.htmlFor = planNameId;
    planName.append(el("span", "field-label", "Plan"));
    const planInput = el("input", "field-input");
    planInput.id = planNameId;
    planInput.name = planNameId;
    planInput.value = humanize(plan.id);
    planName.append(planInput);
    const price = el("label", "field-group field-price");
    const priceId = fixtureDomId(company.name, plan.id, "monthly-price");
    price.htmlFor = priceId;
    price.append(el("span", "field-label", "Monthly price"));
    const priceInput = el("input", "field-input");
    priceInput.id = priceId;
    priceInput.name = priceId;
    priceInput.value = money(plan.price);
    price.append(priceInput);
    planRow.append(planName, price);
    card.append(planRow);

    const segments = el("div", "segment-list");
    plan.segments.forEach((segment) => {
      const item = el("article", "segment");
      const top = el("div", "segment-top");
      top.append(el("h3", "segment-name", humanize(segment.id)), el("span", "customer-count", `${segment.customers} customers`));
      item.append(top);

      const facts = el("div", "plain-facts");
      const sensitivity = el("div", "plain-fact");
      const sensitivityLevel = priceSensitivity(segment.elasticity.mid, jargon.elasticity);
      sensitivity.append(el("span", "fact-label", jargon.elasticity.plain), el("strong", `level level-${sensitivityLevel}`, sensitivityLevel));
      const churn = el("div", "plain-fact");
      churn.append(el("span", "fact-label", jargon.monthly_churn.plain), el("strong", "", `${Math.round(segment.monthly_churn * 100)}%`));
      const attention = el("div", "plain-fact");
      attention.append(el("span", "fact-label", jargon.cross_elasticity.plain), el("strong", "", competitorAttention(segment.cross_elasticity, jargon.cross_elasticity)));
      facts.append(sensitivity, churn, attention);
      item.append(facts);

      const raw = el("div", "advanced-only raw-block");
      raw.append(
        advancedDetail("elasticity", `low ${segment.elasticity.low}, mid ${segment.elasticity.mid}, high ${segment.elasticity.high}`),
        advancedDetail("monthly_churn", String(segment.monthly_churn)),
        advancedDetail("cross_elasticity", String(segment.cross_elasticity)),
      );
      item.append(raw);
      segments.append(item);
    });
    card.append(segments);
  });

  const competitors = el("div", "competitor-strip");
  competitors.append(el("h3", "subheading", "Competitors in view"));
  const list = el("div", "competitor-list");
  company.competitors.forEach((competitor) => {
    const item = el("div", "competitor");
    item.append(el("span", "competitor-name", competitor.name), el("strong", "competitor-price", money(competitor.price)));
    const inputId = fixtureDomId(company.name, competitor.name, "pricing-page");
    const label = el("label", "sr-only", `${competitor.name} pricing page`);
    label.htmlFor = inputId;
    const input = el("input", "competitor-url");
    input.id = inputId;
    input.name = inputId;
    input.value = competitor.url;
    item.append(label, input);
    list.append(item);
  });
  competitors.append(list);
  card.append(competitors);
  content.append(card);
}

function renderTree(tree, jargon) {
  const nodes = new Map(tree.nodes.map((node) => [node.id, node]));
  const root = nodes.get("root") || tree.nodes.find((node) => node.parent === null);
  const competitorResponses = tree.nodes.filter((node) => node.actor === "competitor");
  const content = createMessage(`I mapped ${competitorResponses.length} ways competitors could respond. Open any response to compare your three choices, then select a choice to see its likely result.`);
  const widget = el("section", "tree-widget widget");
  widget.setAttribute("aria-labelledby", "tree-title");

  const heading = el("div", "widget-heading tree-heading");
  const titleWrap = el("div");
  titleWrap.append(el("span", "widget-label", "Response map"), el("h2", "widget-title", "How the market might move"));
  titleWrap.querySelector("h2").id = "tree-title";
  heading.append(titleWrap, el("span", "node-count", `${competitorResponses.length} responses`));
  widget.append(heading);

  const move = el("div", "root-move");
  move.append(el("span", "root-caption", "Your move"), el("strong", "", `${humanize(root.choice)} · ${money(root.price_before)} → ${money(root.price_after)}`));
  move.append(advancedDetail("root hash", root.hash));
  widget.append(move);

  const grouped = competitorResponses.reduce((groups, node) => {
    const name = node.label.split(":")[0];
    if (!groups.has(name)) groups.set(name, []);
    groups.get(name).push(node);
    return groups;
  }, new Map());

  const responseGroups = el("div", "response-groups");
  grouped.forEach((responses, competitor) => {
    const group = el("section", "response-group");
    const groupHeading = el("div", "response-group-heading");
    groupHeading.append(el("h3", "", competitor), el("span", "", `${responses.length} possible responses`));
    group.append(groupHeading);

    const responseList = el("div", "response-list");
    responses.forEach((response) => {
      const details = el("details", "response-node");
      const summary = el("summary", "response-summary");
      const summaryCopy = el("span", "response-copy");
      summaryCopy.append(el("strong", "", humanize(response.choice)), el("span", "", `${money(response.price_before)} → ${money(response.price_after)}`));
      const glyph = el("span", "expand-glyph", "+");
      glyph.setAttribute("aria-hidden", "true");
      summary.append(summaryCopy, glyph);
      details.append(summary);

      const leaves = el("div", "leaf-list");
      response.children.forEach((leafId) => {
        const leaf = nodes.get(leafId);
        const button = el("button", "leaf-button");
        button.type = "button";
        button.dataset.leafId = leaf.id;
        button.setAttribute("aria-pressed", "false");
        button.append(el("span", "leaf-choice", humanize(leaf.choice)), el("span", "leaf-mid", signedPercent(leaf.score.mid_pct)));
        button.addEventListener("click", () => selectLeaf(leaf, widget, jargon));
        leaves.append(button);
      });
      details.append(leaves);
      responseList.append(details);
    });
    group.append(responseList);
    responseGroups.append(group);
  });
  widget.append(responseGroups);

  const selected = el("div", "leaf-result empty");
  selected.id = "leaf-result";
  selected.setAttribute("aria-live", "polite");
  selected.append(el("span", "result-prompt", "Select one of your choices to see the six-month range."));
  widget.append(selected);

  const calculation = el("div", "advanced-only calculation-card");
  calculation.append(el("span", "widget-label", "Scoring script"));
  const code = el("pre", "calculation-code");
  code.textContent = "price_factor = clamp((new_price / old_price) ** elasticity\n  * (new_competitor_average / old_competitor_average) ** cross_elasticity, 0, 1)\nscore_percent = 100 * score / baseline_revenue";
  calculation.append(code);
  widget.append(calculation);
  content.append(widget);
}

function selectLeaf(leaf, widget, jargon) {
  state.selectedLeafId = leaf.id;
  widget.querySelectorAll(".leaf-button").forEach((button) => {
    const selected = button.dataset.leafId === leaf.id;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  const result = widget.querySelector("#leaf-result");
  result.classList.remove("empty");
  result.replaceChildren();
  const label = el("span", "result-label", humanize(leaf.choice));
  const sentence = el("p", "result-sentence", scoreSentence(leaf.score, jargon));
  result.append(label, sentence);
  const raw = el("div", "advanced-only raw-block result-raw");
  raw.append(
    advancedDetail("score dollars", `low ${leaf.score.low}, mid ${leaf.score.mid}, high ${leaf.score.high}`),
    advancedDetail("score percent range", `low ${leaf.score.low_pct}, mid ${leaf.score.mid_pct}, high ${leaf.score.high_pct}`),
  );
  if (leaf.assumptions?.c_prime_convention) raw.append(advancedDetail("c_prime_convention", leaf.assumptions.c_prime_convention));
  result.append(raw);
}

function renderRecommendation(recommendation, jargon) {
  const content = createMessage("The strongest path stays ahead across the full range I checked.");
  const panel = el("section", "recommendation widget");
  panel.setAttribute("aria-labelledby", "recommendation-title");
  panel.append(el("span", "widget-label", "Recommendation"));
  const title = el("h2", "recommendation-title", recommendation.sentence);
  title.id = "recommendation-title";
  panel.append(title);

  const band = el("p", "recommendation-band", scoreSentence(recommendation.band, jargon));
  panel.append(band);

  const reasons = el("div", "recommendation-details");
  const runner = el("article", "recommendation-detail");
  runner.append(el("span", "detail-icon", "2"), el("div", "", ""));
  runner.lastElementChild.append(
    el("h3", "", "Next-best option"),
    el("strong", "runner-up-path", pathDescription(recommendation.runner_up_id)),
    el("p", "", recommendation.runner_up_reason),
  );
  const sensitivity = el("article", "recommendation-detail");
  sensitivity.append(el("span", "detail-icon", "↔"), el("div", "", ""));
  sensitivity.lastElementChild.append(el("h3", "", "How steady is this?"), el("p", "", recommendation.sensitivity.statement.replace("price-sensitivity", jargon.elasticity.plain).replace("sensitivity-ranked", "ranked by sensitivity")));
  const watch = el("article", "recommendation-detail watch-detail");
  watch.append(el("span", "detail-icon", "◇"), el("div", "", ""));
  watch.lastElementChild.append(el("h3", "", "What to watch"), el("p", "", recommendation.watch_trigger.statement));
  reasons.append(runner, sensitivity, watch);
  panel.append(reasons);

  const raw = el("div", "advanced-only raw-block");
  raw.append(
    advancedDetail("path_id", recommendation.path_id),
    advancedDetail("runner_up_id", recommendation.runner_up_id),
    advancedDetail("band range", JSON.stringify(recommendation.band)),
    advancedDetail("flips_ranking", String(recommendation.sensitivity.flips_ranking)),
  );
  panel.append(raw);
  content.append(panel);
}

function renderApproval(action, move, company) {
  const content = createMessage("Nothing changes unless you approve it. Here is the exact change I’m ready to open for review.");
  const card = el("section", "approval-card widget");
  card.setAttribute("aria-labelledby", "approval-title");
  const flag = el("div", "approval-flag");
  flag.append(el("span", "approval-dot"), el("span", "", "Your approval needed"));
  card.append(flag);
  const title = el("h2", "approval-title", action.sentence);
  title.id = "approval-title";
  card.append(title);

  const change = el("div", "change-summary");
  const changeHeading = el("div", "change-heading");
  const filename = action.diff.match(/^--- a\/(.+)$/m)?.[1] || action.diff.match(/^\+\+\+ b\/(.+)$/m)?.[1] || "";
  const plan = company.plans.find((candidate) => candidate.id === move.plan);
  const planName = humanize(plan?.id || move.plan);
  changeHeading.append(el("span", "", "Proposed change"), el("span", "file-name", filename));
  const visualDiff = el("div", "visual-diff");
  const before = el("div", "diff-line removed");
  before.append(el("span", "diff-sign", "−"), el("span", "", `${planName} monthly price`), el("strong", "", money(move.from)));
  const after = el("div", "diff-line added");
  after.append(el("span", "diff-sign", "+"), el("span", "", `${planName} monthly price`), el("strong", "", money(move.to)));
  visualDiff.append(before, after);
  change.append(changeHeading, visualDiff);
  card.append(change);

  const rawDiff = el("details", "raw-diff");
  rawDiff.append(el("summary", "", "View file diff"));
  rawDiff.append(el("pre", "", action.diff));
  card.append(rawDiff);

  const actions = el("div", "approval-actions");
  const approve = el("button", "button button-primary", "Approve");
  approve.type = "button";
  const notNow = el("button", "button button-secondary", "Not now");
  notNow.type = "button";
  actions.append(approve, notNow);
  card.append(actions);

  const raw = el("div", "advanced-only raw-block");
  raw.append(
    advancedDetail("winning_branch_id", action.winning_branch_id),
    advancedDetail("root_hash", action.root_hash),
    advancedDetail("status", action.status),
  );
  card.append(raw);
  content.append(card);
}

function renderTrace(events) {
  const grid = document.querySelector("#trace-grid");
  const columns = [
    { id: "doing", label: "Doing", empty: "Nothing in progress" },
    { id: "waiting", label: "Waiting", empty: "Nothing waiting" },
    { id: "did", label: "Did", empty: "Nothing finished yet" },
  ];
  columns.forEach((column) => {
    const section = el("section", `trace-column trace-${column.id}`);
    const header = el("div", "trace-column-heading");
    header.append(el("span", "trace-status-dot"), el("h3", "", column.label));
    const matching = events.filter((event) => event.column === column.id);
    header.append(el("span", "trace-count", String(matching.length)));
    section.append(header);
    if (!matching.length) section.append(el("p", "trace-empty", column.empty));
    matching.forEach((event) => {
      const item = el("article", "trace-item");
      item.append(el("p", "", event.text));
      const time = new Date(event.ts).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
      item.append(el("time", "", time));
      section.append(item);
    });
    grid.append(section);
  });
}

function applyAdvancedMode(enabled) {
  state.advanced = enabled;
  document.documentElement.classList.toggle("advanced", enabled);
  document.querySelector(".advanced-toggle input").setAttribute("aria-checked", String(enabled));
}

function render(data) {
  state.data = data;
  const feed = document.querySelector("#conversation-feed");
  feed.replaceChildren();
  const advancedToggle = document.querySelector('[data-control="advanced-toggle"]');
  const advancedToggleId = fixtureDomId(data.pendingAction.id, "advanced-toggle");
  advancedToggle.id = advancedToggleId;
  advancedToggle.name = advancedToggleId;
  advancedToggle.closest("label").htmlFor = advancedToggleId;
  createMessage("What is your company website?");
  renderWebsiteMessage(data.company);
  renderCompany(data.company, data.jargon);
  createMessage("What change are you considering?");
  renderUserMessage(data.move);
  renderTree(data.tree, data.jargon);
  renderRecommendation(data.recommendation, data.jargon);
  renderApproval(data.pendingAction, data.move, data.company);
  renderTrace(data.traceEvents);
}

function renderError(error) {
  const feed = document.querySelector("#conversation-feed");
  feed.replaceChildren();
  const errorState = el("div", "error-state");
  errorState.append(el("h2", "", "I couldn’t prepare this decision."), el("p", "", "Start the page from the repository root with Python’s local web server, then refresh."));
  feed.append(errorState);
  console.error("Could not load Countermove fixtures:", error);
}

async function loadFixtures() {
  const entries = await Promise.all(Object.entries(fixtureFiles).map(async ([key, file]) => {
    const response = await fetch(`${FIXTURE_PATH}/${file}`);
    if (!response.ok) throw new Error(`${file} returned ${response.status}`);
    return [key, await response.json()];
  }));
  return Object.fromEntries(entries);
}

document.querySelector('[data-control="advanced-toggle"]').addEventListener("change", (event) => applyAdvancedMode(event.target.checked));
loadFixtures().then(render).catch(renderError);
