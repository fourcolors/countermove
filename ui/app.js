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

const SVG_NS = "http://www.w3.org/2000/svg";
const RESPONSE_CHOICES = ["undercut", "match", "ignore", "raise"];
const GRAPH = {
  padX: 20,
  padY: 18,
  colGap: 32,
  nodeW: { root: 188, response: 196, leaf: 188 },
  nodeH: { root: 52, response: 42, leaf: 36 },
  rowGap: 7,
  leafGap: 6,
};

let graphDismiss = null;

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

function roundedPercentNumber(value) {
  // Display precision only: always one decimal ("+5.0%", "+7.7%").
  const rounded = Math.round(Math.abs(Number(value)) * 10) / 10;
  return rounded.toFixed(1);
}

function signedPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  const number = Number(value);
  const sign = number > 0 ? "+" : number < 0 ? "−" : "";
  return `${sign}${roundedPercentNumber(number)}%`;
}

function signedPercentFixed(value) {
  if (value === null || value === undefined || value === "n/a" || Number.isNaN(Number(value))) return "n/a";
  const number = Number(value);
  const sign = number > 0 ? "+" : number < 0 ? "-" : "";
  return `${sign}${Math.abs(number).toFixed(1)}%`;
}

function signedPercentValue(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  const number = Number(value);
  const sign = number > 0 ? "+" : number < 0 ? "−" : "";
  return `${sign}${roundedPercentNumber(number)}`;
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

function runnerUpLabel(pathId) {
  const match = pathId && String(pathId).match(/^leaf-(rival-[abc])-(undercut|match|ignore|raise)-(hold|partial_rollback|annual_discount)$/);
  if (!match) return humanize(pathId || "the runner-up");
  const competitor = match[1].replace("rival-", "Rival ").toUpperCase().replace("RIVAL", "Rival");
  const choiceVerb = { undercut: "undercuts", match: "matches", ignore: "ignores", raise: "raises" }[match[2]] || match[2];
  const counter = match[3].replaceAll("_", " ");
  return `${counter} after ${competitor} ${choiceVerb}`;
}

function runnerUpSentence(recommendation) {
  const label = runnerUpLabel(recommendation.runner_up_id);
  const winnerPct = recommendation.band && recommendation.band.mid_pct;
  const nodes = state.data && state.data.tree && state.data.tree.nodes;
  const runnerNode = Array.isArray(nodes) ? nodes.find((node) => node.id === recommendation.runner_up_id) : null;
  const runnerPct = runnerNode && runnerNode.score && runnerNode.score.mid_pct;
  const havePercents = winnerPct !== null && winnerPct !== undefined && !Number.isNaN(Number(winnerPct))
    && runnerPct !== null && runnerPct !== undefined && !Number.isNaN(Number(runnerPct));
  if (havePercents) {
    return `The next-best option is ${label}, at ${signedPercent(runnerPct)} versus ${signedPercent(winnerPct)} for the recommended path.`;
  }
  return `The next-best option is ${label}.`;
}

function el(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function svgEl(tag, attrs) {
  const node = document.createElementNS(SVG_NS, tag);
  Object.entries(attrs || {}).forEach(([key, value]) => {
    if (value === undefined || value === null) return;
    node.setAttribute(key, String(value));
  });
  return node;
}

function hasTree(tree) {
  return Boolean(tree && Array.isArray(tree.nodes) && tree.nodes.length);
}

function actorLabel(actor) {
  if (actor === "you") return "You";
  if (actor === "competitor") return "Competitor";
  return humanize(actor || "unknown");
}

function graphChoiceLabel(choice) {
  return ({
    hold: "Hold",
    partial_rollback: "Partial rollback",
    annual_discount: "Annual discount",
    price_change: "Price change",
    undercut: "Undercut",
    match: "Match",
    ignore: "Ignore",
    raise: "Raise",
  })[choice] || humanize(choice);
}

function responseCaption(node) {
  const label = node.label || "";
  const colon = label.indexOf(":");
  if (colon === -1) {
    return { rival: humanize(label), choice: humanize(node.choice) };
  }
  const rival = label.slice(0, colon).trim();
  const choice = label.slice(colon + 1).trim() || humanize(node.choice);
  return { rival, choice };
}

function metricTone(value) {
  const number = Number(value);
  if (value === null || value === undefined || value === "n/a" || Number.isNaN(number) || number === 0) return "zero";
  return number > 0 ? "gain" : "loss";
}

function starIcon() {
  const svg = svgEl("svg", { viewBox: "0 0 24 24", width: "11", height: "11", "aria-hidden": "true" });
  svg.append(svgEl("path", {
    d: "M12 2.6l2.47 6.05 6.53.58-4.97 4.32 1.52 6.38L12 16.9l-5.55 3.03 1.52-6.38-4.97-4.32 6.53-.58z",
  }));
  return svg;
}

function setTruncatedText(element, text) {
  const value = text == null ? "" : String(text);
  element.textContent = value;
  element.title = value;
}

function edgePath(from, to) {
  const x1 = from.x + from.w;
  const y1 = from.y + from.h / 2;
  const x2 = to.x;
  const y2 = to.y + to.h / 2;
  const dx = Math.max(28, (x2 - x1) * 0.55);
  return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
}

function ancestorIds(nodes, startId) {
  const ids = new Set();
  let current = startId;
  while (current && nodes.has(current)) {
    ids.add(current);
    current = nodes.get(current).parent;
  }
  return ids;
}

function formatRate(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function assumptionRows(assumptions) {
  if (!assumptions || typeof assumptions !== "object") return [];
  const rows = [];
  if (assumptions.months != null) rows.push(["Horizon", `${assumptions.months} months`]);
  const before = assumptions.competitor_average_before;
  const after = assumptions.competitor_average_after;
  if (before != null && after != null) {
    rows.push(["Competitor average", `${money(before)} → ${money(after)}`]);
  } else if (after != null) {
    rows.push(["Competitor average after", money(after)]);
  } else if (before != null) {
    rows.push(["Competitor average before", money(before)]);
  }
  if (assumptions.c_prime_convention) {
    rows.push(["Average convention", String(assumptions.c_prime_convention)]);
  }
  const counter = assumptions.counter;
  if (counter && typeof counter === "object") {
    const bits = [];
    if (counter.choice) bits.push(humanize(counter.choice));
    if (counter.rollback_fraction != null) bits.push(`${formatRate(counter.rollback_fraction)} rollback`);
    if (counter.discount_rate != null) bits.push(`${formatRate(counter.discount_rate)} discount`);
    if (counter.uptake != null) bits.push(`${formatRate(counter.uptake)} uptake`);
    if (bits.length) rows.push(["Counter", bits.join(" · ")]);
  }
  return rows;
}

function detailRow(term, value, extraClass) {
  const row = el("div", "tree-detail-row");
  const text = el("span", extraClass ? `tree-detail-value ${extraClass}` : "tree-detail-value", value);
  row.append(el("span", "tree-detail-term", term), text);
  return row;
}

function layoutGraph(root, responses, nodes, expanded) {
  const positions = new Map();
  const rootX = GRAPH.padX;
  const respX = GRAPH.padX + GRAPH.nodeW.root + GRAPH.colGap;
  const leafX = respX + GRAPH.nodeW.response + GRAPH.colGap;
  let y = GRAPH.padY;

  responses.forEach((response) => {
    const open = expanded.has(response.id);
    const leaves = open
      ? (response.children || []).map((id) => nodes.get(id)).filter(Boolean)
      : [];
    const leafStack = leaves.length
      ? leaves.length * GRAPH.nodeH.leaf + (leaves.length - 1) * GRAPH.leafGap
      : 0;
    const blockH = Math.max(GRAPH.nodeH.response, leafStack || GRAPH.nodeH.response);
    positions.set(response.id, {
      x: respX,
      y: y + (blockH - GRAPH.nodeH.response) / 2,
      w: GRAPH.nodeW.response,
      h: GRAPH.nodeH.response,
      kind: "response",
    });
    if (leaves.length) {
      let leafY = y + (blockH - leafStack) / 2;
      leaves.forEach((leaf) => {
        positions.set(leaf.id, {
          x: leafX,
          y: leafY,
          w: GRAPH.nodeW.leaf,
          h: GRAPH.nodeH.leaf,
          kind: "leaf",
        });
        leafY += GRAPH.nodeH.leaf + GRAPH.leafGap;
      });
    }
    y += blockH + GRAPH.rowGap;
  });

  const contentH = Math.max(GRAPH.nodeH.root, y - GRAPH.rowGap - GRAPH.padY);
  positions.set(root.id, {
    x: rootX,
    y: GRAPH.padY + Math.max(0, (contentH - GRAPH.nodeH.root) / 2),
    w: GRAPH.nodeW.root,
    h: GRAPH.nodeH.root,
    kind: "root",
  });
  const bottom = Math.max(
    GRAPH.padY + contentH,
    [...positions.values()].reduce((max, box) => Math.max(max, box.y + box.h), 0),
  );
  return {
    positions,
    width: leafX + GRAPH.nodeW.leaf + GRAPH.padX,
    height: bottom + GRAPH.padY,
    respX,
    leafX,
  };
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
  const content = createMessage(`The same ${competitorResponses.length} responses are listed below if you want to compare your three counters in one place.`);
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

  if (state.selectedLeafId) {
    const selected = nodes.get(state.selectedLeafId);
    if (selected) selectLeaf(selected, widget, jargon);
  }
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

function renderDecisionGraph(tree, recommendation, jargon) {
  if (!hasTree(tree)) return;
  if (graphDismiss) {
    graphDismiss.abort();
    graphDismiss = null;
  }

  const nodes = new Map(tree.nodes.map((node) => [node.id, node]));
  const root = nodes.get(tree.root) || nodes.get("root") || tree.nodes.find((node) => node.parent === null);
  if (!root) return;

  const responses = (root.children || []).map((id) => nodes.get(id)).filter(Boolean);
  if (!responses.length) {
    tree.nodes.filter((node) => node.actor === "competitor").forEach((node) => responses.push(node));
  }
  if (!responses.length) return;

  const winId = recommendation?.highlighted_path_id || recommendation?.path_id || null;
  const runnerId = recommendation?.runner_up_id && recommendation.runner_up_id !== winId
    ? recommendation.runner_up_id
    : null;
  const golden = winId ? ancestorIds(nodes, winId) : new Set();
  const winNode = winId ? nodes.get(winId) : null;
  const expanded = new Set();
  if (winNode?.parent) expanded.add(winNode.parent);
  if (winId) state.selectedLeafId = winId;

  const content = createMessage("Follow each choice from your move, through a competitor response, to your counter. The recommended path is marked.");
  const widget = document.querySelector("#decision-tree-template").content.firstElementChild.cloneNode(true);
  const count = widget.querySelector("[data-tree-count]");
  count.textContent = `${responses.length} responses`;
  const stage = widget.querySelector("[data-tree-stage]");
  const detail = widget.querySelector("[data-tree-detail]");
  const detailActor = widget.querySelector("[data-tree-detail-actor]");
  const detailLabel = widget.querySelector("[data-tree-detail-label]");
  const detailBody = widget.querySelector("[data-tree-detail-body]");
  const closeButton = widget.querySelector("[data-tree-detail-close]");

  function hideDetail() {
    detail.hidden = true;
    detailActor.textContent = "";
    detailLabel.textContent = "";
    detailBody.replaceChildren();
  }

  function showDetail(node) {
    const fullLabel = node.label && node.label !== node.choice
      ? node.label
      : humanize(node.choice || node.label);
    setTruncatedText(detailLabel, fullLabel);
    detailActor.textContent = actorLabel(node.actor);
    detailBody.replaceChildren();
    detailBody.append(
      detailRow("Actor", actorLabel(node.actor)),
      detailRow("Price", `${money(node.price_before)} → ${money(node.price_after)}`),
    );
    const reason = el("div", "tree-detail-row");
    const reasonText = el("span", "tree-detail-value tree-detail-reason");
    reasonText.textContent = node.reasoning || "No reasoning recorded.";
    reason.append(el("span", "tree-detail-term", "Reasoning"), reasonText);
    detailBody.append(reason);
    const score = node.score;
    if (score && typeof score === "object") {
      const band = `low ${signedPercentFixed(score.low_pct)} · mid ${signedPercentFixed(score.mid_pct)} · high ${signedPercentFixed(score.high_pct)}`;
      detailBody.append(detailRow("Score band", band, "tree-detail-band"));
    }
    const assumptionSummary = assumptionRows(node.assumptions);
    if (assumptionSummary.length) {
      assumptionSummary.forEach(([term, value]) => detailBody.append(detailRow(term, value)));
    } else {
      detailBody.append(detailRow("Assumptions", "No extra assumptions recorded."));
    }
    const sourceCount = Array.isArray(node.sources) ? node.sources.length : 0;
    detailBody.append(detailRow("Sources", sourceCount === 1 ? "1 source" : `${sourceCount} sources`));
    detail.hidden = false;
  }

  function paint(focusId) {
    const layout = layoutGraph(root, responses, nodes, expanded);
    stage.style.width = `${layout.width}px`;
    stage.style.height = `${layout.height}px`;
    stage.replaceChildren();

    const svg = svgEl("svg", {
      class: "decision-tree-edges",
      viewBox: `0 0 ${layout.width} ${layout.height}`,
      width: String(layout.width),
      height: String(layout.height),
      "aria-hidden": "true",
    });
    const normalGroup = svgEl("g", { class: "graph-edges" });
    const goldenGroup = svgEl("g", { class: "graph-edges-golden" });

    function connect(parentId, childId) {
      const from = layout.positions.get(parentId);
      const to = layout.positions.get(childId);
      if (!from || !to) return;
      const isGolden = golden.has(parentId) && golden.has(childId);
      const path = svgEl("path", {
        class: isGolden ? "graph-edge graph-edge-golden" : "graph-edge",
        d: edgePath(from, to),
      });
      (isGolden ? goldenGroup : normalGroup).append(path);
    }

    responses.forEach((response) => {
      connect(root.id, response.id);
      if (!expanded.has(response.id)) return;
      (response.children || []).forEach((leafId) => connect(response.id, leafId));
    });
    svg.append(normalGroup, goldenGroup);
    stage.append(svg);

    const visible = [root, ...responses];
    responses.forEach((response) => {
      if (!expanded.has(response.id)) return;
      (response.children || []).forEach((leafId) => {
        const leaf = nodes.get(leafId);
        if (leaf) visible.push(leaf);
      });
    });

    visible.forEach((node) => {
      const box = layout.positions.get(node.id);
      if (!box) return;
      const kind = box.kind;
      const button = el("button", `graph-node graph-node-${kind}`);
      button.type = "button";
      button.tabIndex = 0;
      button.dataset.nodeId = node.id;
      button.style.left = `${box.x}px`;
      button.style.top = `${box.y}px`;
      button.style.width = `${box.w}px`;
      button.style.height = `${box.h}px`;

      if (golden.has(node.id)) button.classList.add("graph-node-golden");
      if (kind === "leaf" && node.id === runnerId) button.classList.add("graph-node-runner");
      if (kind === "response" && !expanded.has(node.id) && runnerId && nodes.get(runnerId)?.parent === node.id) {
        button.classList.add("graph-node-runner");
      }
      if (kind === "leaf" && node.id === state.selectedLeafId) button.classList.add("is-selected");
      if (kind === "response" && expanded.has(node.id)) button.classList.add("is-expanded");

      if (kind === "root") {
        const copy = el("span", "graph-node-copy");
        copy.append(el("span", "graph-node-kicker", "Your move"));
        const label = el("span", "graph-node-label");
        setTruncatedText(label, node.label || humanize(node.choice));
        copy.append(label);
        button.append(copy);
        button.setAttribute("aria-label", `Your move: ${node.label || humanize(node.choice)}`);
      } else if (kind === "response") {
        const parts = responseCaption(node);
        const choice = RESPONSE_CHOICES.includes(node.choice) ? node.choice : "ignore";
        const dot = el("span", `choice-dot choice-${choice}`);
        dot.setAttribute("aria-hidden", "true");
        const copy = el("span", "graph-node-copy");
        const rival = el("span", "graph-node-kicker");
        const choiceLine = el("span", "graph-node-label");
        const choiceText = graphChoiceLabel(node.choice);
        setTruncatedText(rival, parts.rival);
        setTruncatedText(choiceLine, choiceText);
        copy.append(rival, choiceLine);
        const glyph = el("span", "expand-glyph", "+");
        glyph.setAttribute("aria-hidden", "true");
        button.append(dot, copy, glyph);
        button.setAttribute("aria-expanded", String(expanded.has(node.id)));
        button.setAttribute("aria-label", `${parts.rival}: ${choiceText}`);
        button.title = `${parts.rival}: ${choiceText}`;
      } else {
        const copy = el("span", "graph-node-copy");
        const label = el("span", "graph-node-label");
        const choiceText = graphChoiceLabel(node.choice);
        setTruncatedText(label, choiceText);
        copy.append(label);
        const mid = node.score ? node.score.mid_pct : null;
        const metric = el("span", `graph-node-metric graph-metric-${metricTone(mid)}`, signedPercentFixed(mid));
        button.append(copy, metric);
        button.setAttribute("aria-pressed", String(node.id === state.selectedLeafId));
        button.setAttribute("aria-label", `${choiceText} ${signedPercentFixed(mid)}`);
        button.title = `${humanize(node.choice)} ${signedPercentFixed(mid)}`;
      }

      if (node.id === winId) {
        const mark = el("span", "graph-mark graph-mark-win");
        mark.title = "Recommended";
        mark.setAttribute("aria-label", "Recommended");
        mark.append(starIcon());
        button.append(mark);
      } else if (node.id === runnerId) {
        const mark = el("span", "graph-mark graph-mark-runner", "2");
        mark.title = "Next-best option";
        mark.setAttribute("aria-label", "Next-best option");
        button.append(mark);
      } else if (kind === "response" && runnerId && nodes.get(runnerId)?.parent === node.id && !expanded.has(node.id)) {
        const mark = el("span", "graph-mark graph-mark-runner", "2");
        mark.title = "Next-best option is in this response";
        mark.setAttribute("aria-label", "Next-best option is in this response");
        button.append(mark);
      }

      button.addEventListener("click", (event) => {
        event.stopPropagation();
        if (kind === "response") {
          if (expanded.has(node.id)) expanded.delete(node.id);
          else expanded.add(node.id);
          paint(node.id);
        } else if (kind === "leaf") {
          state.selectedLeafId = node.id;
          const listWidget = document.querySelector(".tree-widget");
          if (listWidget) selectLeaf(node, listWidget, jargon);
          paint(node.id);
        }
        showDetail(node);
      });
      stage.append(button);
    });

    if (focusId) {
      const focused = stage.querySelector(`[data-node-id="${CSS.escape(focusId)}"]`);
      if (focused) focused.focus();
    }
  }

  closeButton.addEventListener("click", (event) => {
    event.stopPropagation();
    hideDetail();
  });
  detail.addEventListener("click", (event) => event.stopPropagation());

  graphDismiss = new AbortController();
  document.addEventListener("click", (event) => {
    if (detail.hidden) return;
    if (event.target.closest("[data-tree-detail]") || event.target.closest(".graph-node")) return;
    hideDetail();
  }, { signal: graphDismiss.signal });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") hideDetail();
  }, { signal: graphDismiss.signal });

  paint();
  content.append(widget);
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
    el("p", "", runnerUpSentence(recommendation)),
    el("p", "advanced-only", recommendation.runner_up_reason),
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

function approvalChangeSummary(action, move, company) {
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
  return change;
}

function approvalRaw(action) {
  const raw = el("div", "advanced-only raw-block");
  raw.append(
    advancedDetail("winning_branch_id", action.winning_branch_id),
    advancedDetail("root_hash", action.root_hash),
    advancedDetail("status", action.status),
  );
  return raw;
}

function approvalBranchName(action) {
  if (action.branch) return action.branch;
  const url = action.pr_url;
  if (typeof url === "string" && url.startsWith("local://pull/")) return url.slice("local://pull/".length);
  return "";
}

function bindWaitingActions(actions, action) {
  const approve = el("button", "button button-primary", "Approve");
  approve.type = "button";
  const notNow = el("button", "button button-secondary", "Not now");
  notNow.type = "button";
  approve.addEventListener("click", () => gateCall("/gate/allow", action.id, approve));
  notNow.addEventListener("click", () => {
    const form = el("div", "approval-actions deny-form");
    const input = el("input", "field-input");
    input.type = "text";
    input.value = "holding until next month";
    input.setAttribute("aria-label", "Reason for declining");
    const confirmDecline = el("button", "button button-primary", "Confirm decline");
    confirmDecline.type = "button";
    const cancel = el("button", "button button-secondary", "Cancel");
    cancel.type = "button";
    confirmDecline.addEventListener("click", () => {
      const reason = input.value.trim() || "holding until next month";
      gateCall("/gate/deny", action.id, confirmDecline, reason);
    });
    cancel.addEventListener("click", () => form.replaceWith(actions));
    form.append(input, confirmDecline, cancel);
    actions.replaceWith(form);
  });
  actions.replaceChildren(approve, notNow);
}

function renderApproval(action, move, company) {
  document.querySelectorAll(".approval-card").forEach((card) => {
    const message = card.closest(".message");
    if (message) message.remove();
    else card.remove();
  });
  const status = action && action.status;
  const intro = status === "approved"
    ? "The change request is open."
    : status === "denied"
      ? "This request was declined."
      : "Nothing changes unless you approve it. Here is the exact change I’m ready to open for review.";
  const content = createMessage(intro);
  const card = el("section", "approval-card widget");
  card.dataset.actionId = action.id;
  card.setAttribute("aria-labelledby", "approval-title");

  if (status === "approved") {
    card.classList.add("approved");
    const flag = el("div", "approval-flag");
    flag.append(el("span", "approval-dot"), el("span", "", "Approved"));
    card.append(flag);
    const title = el("h2", "approval-title", "Change request opened");
    title.id = "approval-title";
    card.append(title);
    card.append(approvalChangeSummary(action, move, company));
    const branch = approvalBranchName(action);
    if (branch) card.append(el("p", "approval-branch", `Branch ${branch}`));
    else if (action.pr_url) card.append(el("p", "approval-branch", action.pr_url));
    const rawDiff = el("details", "advanced-only raw-diff");
    rawDiff.append(el("summary", "", "View file diff"));
    rawDiff.append(el("pre", "", action.diff));
    card.append(rawDiff, approvalRaw(action));
  } else if (status === "denied") {
    card.classList.add("denied");
    const flag = el("div", "approval-flag");
    flag.append(el("span", "approval-dot"), el("span", "", "Declined"));
    card.append(flag);
    const title = el("h2", "approval-title", "Change request declined");
    title.id = "approval-title";
    card.append(title);
    card.append(approvalChangeSummary(action, move, company));
    if (action.deny_reason) card.append(el("p", "deny-reason", `Reason: ${action.deny_reason}`));
    card.append(el("p", "approval-hint", "Running a new simulation queues a fresh request."));
    const rawDiff = el("details", "advanced-only raw-diff");
    rawDiff.append(el("summary", "", "View file diff"));
    rawDiff.append(el("pre", "", action.diff));
    card.append(rawDiff, approvalRaw(action));
  } else {
    const flag = el("div", "approval-flag");
    flag.append(el("span", "approval-dot"), el("span", "", "Your approval needed"));
    card.append(flag);
    const title = el("h2", "approval-title", action.sentence);
    title.id = "approval-title";
    card.append(title);
    card.append(approvalChangeSummary(action, move, company));
    const rawDiff = el("details", "advanced-only raw-diff");
    rawDiff.append(el("summary", "", "View file diff"));
    rawDiff.append(el("pre", "", action.diff));
    card.append(rawDiff);
    const actions = el("div", "approval-actions");
    bindWaitingActions(actions, action);
    card.append(actions, approvalRaw(action));
  }

  content.append(card);
  const host = document.querySelector("#approval-host");
  const message = content.closest(".message");
  if (host && message) host.replaceChildren(message);
}

function renderTrace(events) {
  const grid = document.querySelector("#trace-grid");
  grid.replaceChildren();
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
  if (graphDismiss) {
    graphDismiss.abort();
    graphDismiss = null;
  }
  const feed = document.querySelector("#conversation-feed");
  feed.replaceChildren();
  const traceGrid = document.querySelector("#trace-grid");
  if (traceGrid) traceGrid.replaceChildren();
  const advancedToggle = document.querySelector('[data-control="advanced-toggle"]');
  const advancedToggleId = fixtureDomId(data.pendingAction.id, "advanced-toggle");
  advancedToggle.id = advancedToggleId;
  advancedToggle.name = advancedToggleId;
  advancedToggle.closest("label").htmlFor = advancedToggleId;
  if (data.isExample) {
    const banner = el("p", "example-banner",
      "This is an example decision so you can see the shape. Type your own move at the bottom and I will run it for real.");
    feed.append(banner);
  }
  createMessage("What is your company website?");
  renderWebsiteMessage(data.company);
  renderCompany(data.company, data.jargon);
  createMessage("What change are you considering?");
  renderUserMessage(data.move);
  renderRecommendation(data.recommendation, data.jargon);
  renderDecisionGraph(data.tree, data.recommendation, data.jargon);
  if (hasTree(data.tree)) renderTree(data.tree, data.jargon);
  const approvalHost = el("div", "");
  approvalHost.id = "approval-host";
  feed.append(approvalHost);
  renderApproval(data.pendingAction, data.move, data.company);
  renderTrace(data.traceEvents);
  renderComposer();
}

function renderComposer() {
  const feed = document.querySelector("#conversation-feed");
  const form = el("form", "composer");
  const input = el("input", "composer-input");
  input.type = "text";
  input.id = "composer-input";
  input.name = "composer-input";
  input.placeholder = 'Try a move: "Raise Pro from $49 to $59 effective 2026-09-07"';
  input.setAttribute("aria-label", "Describe the move you are considering");
  const button = el("button", "button button-primary", "Simulate");
  button.type = "submit";
  form.append(input, button);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const sentence = input.value.trim();
    if (!sentence) return;
    button.disabled = true;
    input.disabled = true;
    button.textContent = "Simulating";
    document.querySelectorAll(".approval-card button").forEach((btn) => { btn.disabled = true; });
    const status = el("p", "composer-status",
      "Checking competitor pages, mapping responses, and scoring every path - a few seconds.");
    form.after(status);
    try {
      const response = await fetch("/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sentence }),
      });
      const body = await response.json();
      if (!body.ok && body.reply) {
        status.remove();
        const feed = document.querySelector("#conversation-feed");
        const userArticle = el("article", "message message-user");
        const userContent = el("div", "message-content");
        userContent.append(el("p", "message-copy", sentence));
        userArticle.append(userContent, el("div", "avatar avatar-user", "You"));
        feed.append(userArticle);
        createMessage(body.reply);
        feed.append(form);
        button.disabled = false;
        input.disabled = false;
        button.textContent = "Simulate";
        document.querySelectorAll(".approval-card button").forEach((btn) => { btn.disabled = false; });
        input.focus();
        return;
      }
      if (!body.ok) throw new Error(body.error || "the simulation could not run");
      render(await loadData());
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (error) {
      status.textContent = String(error.message || error);
      status.classList.add("composer-error");
      button.disabled = false;
      input.disabled = false;
      button.textContent = "Simulate";
      document.querySelectorAll(".approval-card button").forEach((btn) => { btn.disabled = false; });
    }
  });
  feed.append(form);
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

function showGateNotice(button, text) {
  const card = button && button.closest && button.closest(".approval-card");
  if (!card) return;
  card.querySelector(".gate-notice")?.remove();
  const notice = el("div", "gate-notice");
  notice.setAttribute("role", "alert");
  notice.append(el("p", "", text));
  const dismiss = el("button", "button button-secondary", "Dismiss");
  dismiss.type = "button";
  dismiss.addEventListener("click", () => notice.remove());
  notice.append(dismiss);
  card.append(notice);
}

async function gateCall(path, actionId, button, reason) {
  button.disabled = true;
  const original = button.textContent;
  button.textContent = "Working";
  try {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(reason === undefined ? { action_id: actionId } : { action_id: actionId, reason }),
    });
    const body = await response.json();
    if (!body.ok) {
      const serverError = body.error || "the gate refused the request";
      const notice = /not waiting/i.test(serverError)
        ? "That request was already decided - run a new simulation."
        : serverError.replace(/^GateRefused:\s*/, "");
      showGateNotice(button, notice);
      throw new Error(serverError);
    }
    const data = await loadData();
    render(data);
  } catch (error) {
    button.disabled = false;
    button.textContent = original;
    console.error("gate call failed:", error);
  }
}

function sessionToData(session, jargon, fallback) {
  const decisions = session.decisions || [];
  const pendingAction = [...decisions].reverse().find((d) => d && d.status === "waiting")
    || [...decisions].reverse().find((d) => d && d.status)
    || fallback.pendingAction;
  return {
    company: session.company || fallback.company,
    move: session.move || fallback.move,
    tree: session.tree || fallback.tree,
    recommendation: session.recommendation || fallback.recommendation,
    pendingAction,
    personas: session.persona_cards && session.persona_cards.length ? session.persona_cards : fallback.personas,
    scoreResult: fallback.scoreResult,
    traceEvents: session.trace && session.trace.length ? session.trace : fallback.traceEvents,
    jargon,
  };
}

async function loadData() {
  const fixtures = await loadFixtures();
  try {
    const response = await fetch("/session/session.json", { cache: "no-store" });
    if (response.ok) {
      const session = await response.json();
      if (session && session.tree) {
        const data = sessionToData(session, fixtures.jargon, fixtures);
        data.isExample = false;
        return data;
      }
    }
  } catch (error) {
    console.info("no live session; rendering fixtures", error);
  }
  fixtures.isExample = true;
  return fixtures;
}

document.querySelector('[data-control="advanced-toggle"]').addEventListener("change", (event) => applyAdvancedMode(event.target.checked));
loadData().then(render).catch(renderError);
