/* ══════════════════════════════════════════════════════════════
   HomeIntent — Website
   ══════════════════════════════════════════════════════════════ */
(() => {
'use strict';

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const sleep = ms => new Promise(r => setTimeout(r, reduced ? Math.min(ms, 60) : ms));

/* ── Navigation ──────────────────────────────────────────── */
const nav = $('#nav');
const onScroll = () => nav.classList.toggle('stuck', scrollY > 24);
addEventListener('scroll', onScroll, { passive: true });
onScroll();

const burger = $('#burger');
burger.addEventListener('click', () => {
  const open = nav.classList.toggle('open');
  burger.setAttribute('aria-expanded', String(open));
});
$$('.nav__links a').forEach(a => a.addEventListener('click', () => {
  nav.classList.remove('open');
  burger.setAttribute('aria-expanded', 'false');
}));

/* ── Scroll-Reveal ───────────────────────────────────────── */
const io = new IntersectionObserver(entries => {
  for (const e of entries) {
    if (!e.isIntersecting) continue;
    e.target.classList.add('in');
    io.unobserve(e.target);
  }
}, { rootMargin: '0px 0px -12% 0px', threshold: 0.06 });
$$('.reveal').forEach(el => io.observe(el));

/* ── Zähler ──────────────────────────────────────────────── */
const fmt = n => n.toLocaleString('de-DE');
const countIO = new IntersectionObserver(entries => {
  for (const e of entries) {
    if (!e.isIntersecting) continue;
    countIO.unobserve(e.target);
    const el = e.target;
    const to = +el.dataset.count;
    const suffix = el.dataset.suffix || '';
    if (to === 0 || reduced) { el.textContent = fmt(to) + suffix; continue; }
    const dur = 1500, t0 = performance.now();
    const tick = now => {
      const p = Math.min(1, (now - t0) / dur);
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = fmt(Math.round(to * eased)) + suffix;
      if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }
}, { threshold: 0.5 });
$$('[data-count]').forEach(el => countIO.observe(el));

/* ── Kopieren ────────────────────────────────────────────── */
$$('.copy').forEach(box => {
  const btn = $('button', box);
  btn.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(box.dataset.copy);
      box.classList.add('done');
      btn.textContent = 'kopiert';
      setTimeout(() => { box.classList.remove('done'); btn.textContent = 'kopieren'; }, 1800);
    } catch { btn.textContent = 'Strg+C'; }
  });
});

/* ══════════════════════════════════════════════════════════
   Hero — lebende Konversation
   ══════════════════════════════════════════════════════════ */
const SCENES = [
  { me: 'Fahre alle Rollläden im Erdgeschoss hoch.',
    sys: 'cover.open_cover · 4 Ziele · Risiko mittel',
    ha: 'Okay, ich fahre 4 Rollläden hoch.', ms: '0,08 ms' },
  { me: 'Spielt das Radio in der Küche?',
    sys: 'Query-Pfad · kein Serviceplan erzeugt',
    ha: 'Ja, Radio Küche spielt gerade.', ms: '0,05 ms' },
  { me: 'Mach das Licht heller.',
    sys: 'zwei gleichwertige Ziele · wird nicht geraten',
    ha: 'Meinst du Küchenlicht oder Flurlicht?', ms: '0,06 ms' },
  { me: 'Entriegle die Haustür.',
    sys: 'Risiko KRITISCH · Bestätigung erforderlich',
    ha: 'Soll ich die Haustür wirklich entriegeln?', ms: '0,07 ms' },
  { me: 'Was hast du verstanden?',
    sys: 'Erklärung aus aufgelösten Fakten · keine Aktion',
    ha: 'Aktion: entriegeln; Ziel: Haustür; Risiko: kritisch; Status: wartet auf Bestätigung.', ms: '0,02 ms' },
  { me: 'Wie wird das Wetter morgen?',
    sys: 'Haushaltsabfrage · forecast-Attribut · rein lesend',
    ha: 'Morgen wird es bewölkt, bis 19 Grad, mindestens 11 Grad.', ms: '0,04 ms' },
  { me: 'Wer ist zuhause?',
    sys: 'person-Domäne · kein Serviceplan erzeugt',
    ha: 'Zuhause: Philipp.', ms: '0,03 ms' }
];

const chatBody = $('#chatBody'), chatMs = $('#chatMs'), chatBadge = $('#chatBadge');

function addMsg(kind, text = '') {
  const el = document.createElement('div');
  el.className = 'msg msg--' + kind;
  el.textContent = text;
  chatBody.append(el);
  while (chatBody.children.length > 6) chatBody.firstElementChild.remove();
  return el;
}

async function type(el, text, speed = 26) {
  const cur = document.createElement('span');
  cur.className = 'cursor';
  el.append(cur);
  for (const ch of text) {
    cur.before(document.createTextNode(ch));
    await sleep(speed + Math.random() * 22);
  }
  cur.remove();
}

async function runChat() {
  let i = 0;
  for (;;) {
    const s = SCENES[i % SCENES.length];
    if (i % SCENES.length === 0) { chatBody.innerHTML = ''; }

    const me = addMsg('me');
    await type(me, s.me);
    await sleep(320);

    chatBadge.textContent = 'analysiert';
    const sys = addMsg('sys', s.sys);
    sys.style.opacity = 0;
    requestAnimationFrame(() => { sys.style.transition = 'opacity .4s'; sys.style.opacity = 1; });
    await sleep(760);

    chatBadge.textContent = 'lokal';
    chatMs.textContent = s.ms;
    const ha = addMsg('ha');
    await type(ha, s.ha, 16);

    await sleep(2600);
    i++;
  }
}
if (chatBody) runChat();

/* ══════════════════════════════════════════════════════════
   Live-Pipeline
   ══════════════════════════════════════════════════════════ */
const S = (t, v) => ({ t, v });

const EXAMPLES = [
  {
    tag: 'Befehl mit Ausschluss',
    text: 'Schalte alle Lichter im Erdgeschoss aus, außer der Stehlampe.',
    stages: [
      S('Normalisierung', 'Kleinschreibung, Satzzeichen und Zahlwörter werden kanonisiert. Der Rohtext bleibt für die Erklärung erhalten.'),
      S('Äußerungsanalyse', 'Sprechakt <code>COMMAND</code> · Modalität direkt · Polarität positiv · <code>safe_to_execute_directly = true</code>'),
      S('Semantisches Lexikon', 'Aktionsmarker <code>ausschalten</code> · Quantor <code>alle</code> · Domänenwort <code>Lichter</code> · Ausnahmeklausel erkannt'),
      S('Semantic Frame', 'action <code>turn_off</code> · domain <code>light</code> · floor <code>Erdgeschoss</code> · quantifier <code>ALL</code> · exclude <code>[Stehlampe]</code>'),
      S('World Model', 'Drei für Assist freigegebene Lichter im Erdgeschoss: Küchenlicht, Flurlicht, Stehlampe.'),
      S('Entity-Auflösung', '„Stehlampe“ ist eindeutig → <code>light.wohnzimmer_stehlampe</code> und wird <b>vor</b> der Planung aus der Zielmenge entfernt.'),
      S('Capability-Prüfung', 'Beide verbleibenden Ziele melden <code>turn_off</code> als unterstützte Fähigkeit.'),
      S('Execution Policy', 'Domäne <code>light</code> = Risiko niedrig · 2 Ziele unter dem Grenzwert · keine Bestätigung nötig.')
    ],
    kind: 'plan', tagText: 'ServiceCallPlan', meta: 'ausgeführt',
    say: 'Okay, ich schalte 2 Lichter aus.',
    plan: [['Dienst', 'light.turn_off'], ['Ziele', 'light.kueche, light.flur'],
           ['Ausgenommen', 'light.wohnzimmer_stehlampe'], ['Risiko', 'niedrig'], ['Bestätigung', 'nicht erforderlich']],
    why: '<b>Warum das sicher ist:</b> Die Ausnahme wird aufgelöst, bevor überhaupt ein Plan entsteht. Wäre „Stehlampe“ mehrdeutig gewesen, hätte HomeIntent nachgefragt statt eine Auswahl zu treffen.'
  },
  {
    tag: 'Frage — Regel R3',
    text: 'Ist im Bad noch Licht an?',
    stages: [
      S('Normalisierung', 'Fragezeichen und Partikel bleiben als Signal erhalten, statt weggeworfen zu werden.'),
      S('Äußerungsanalyse', 'Sprechakt <code>QUERY</code> · das Verb <code>ist</code> und die Satzstellung markieren eine Zustandsfrage.'),
      S('Semantisches Lexikon', 'Zustandsprädikat <code>an</code> · Ort <code>Bad</code> · Domäne <code>light</code> · kein Aktionsmarker vorhanden.'),
      S('Semantic Frame', 'intent <code>QUERY_STATE</code> · predicate <code>on</code> · area <code>Bad</code> — <b>kein</b> action-Feld.'),
      S('World Model', 'Ein Licht im Bereich Bad freigegeben: <code>light.bad</code>, aktueller Zustand <code>off</code>.'),
      S('Query-Grenze (R3)', 'Der Query-Pfad kann strukturell keinen <code>ServiceCallPlan</code> erzeugen. Diese Grenze wird von 1.536 generierten Testfällen überwacht.'),
      S('Wahrheitswert', 'Zustand eindeutig ablesbar → <code>FALSE</code>. Wäre er es nicht, gäbe es ausdrücklich <code>UNKNOWN</code> statt eines erfundenen „Nein“.')
    ],
    kind: 'query', tagText: 'QueryResult', meta: 'rein lesend',
    say: 'Nein, das Badlicht ist aus.',
    plan: [['Dienst', '— kein Serviceaufruf —'], ['Gelesen', 'light.bad = off'], ['Wahrheitswert', 'FALSE'], ['Zustandsänderung', 'keine']],
    why: '<b>Architekturregel R3:</b> Eine Frage erzeugt niemals einen Serviceplan — auch dann nicht, wenn die Formulierung einem Befehl ähnelt. Frage- und Befehlspfad sind getrennte Codewege.'
  },
  {
    tag: 'Mehrdeutigkeit — Regel R4',
    text: 'Stell das Radio lauter.',
    stages: [
      S('Normalisierung', 'Der Komparativ <code>lauter</code> wird als relative Abstufung mit festem Schritt erkannt.'),
      S('Äußerungsanalyse', 'Sprechakt <code>COMMAND</code> · direkt · positiv.'),
      S('Semantisches Lexikon', 'Aktion <code>volume_up</code> · Domänenwort <code>Radio</code> · kein Ort, kein Eigenname.'),
      S('Semantic Frame', 'action <code>volume_set</code> (relativ, +10 %) · domain <code>media_player</code> · target unbestimmt.'),
      S('World Model', 'Zwei Media Player freigegeben: <code>media_player.radio_kueche</code>, <code>media_player.radio_bad</code>.'),
      S('Entity-Auflösung', 'Beide Kandidaten erreichen denselben Bewertungswert → Status <code>AMBIGUOUS</code>.'),
      S('Regel R4', 'Bei echter Mehrdeutigkeit wird nicht geraten. Die erste gefundene Entität zu nehmen wäre reproduzierbar — aber reproduzierbar falsch.')
    ],
    kind: 'ask', tagText: 'Rückfrage', meta: 'nichts ausgeführt',
    say: 'Meinst du Radio Küche oder Radio Bad?',
    plan: [['Dienst', '— nicht erzeugt —'], ['Kandidaten', 'radio_kueche, radio_bad'], ['Status', 'AMBIGUOUS'], ['Kontext', '30 s gültig für die Antwort']],
    why: '<b>Der Dialogkontext merkt sich die geprüfte Aktion.</b> Antwortest du „die Küche“, wird nur das Ziel ersetzt — die bereits validierte Operation bleibt bestehen und wird nicht neu geraten.'
  },
  {
    tag: 'Höflichkeit statt Schablone',
    text: 'Wäre es möglich, das Küchenlicht einzuschalten?',
    stages: [
      S('Normalisierung', 'Die Höflichkeitshülle wird nicht abgeschnitten, sondern analysiert.'),
      S('Äußerungsanalyse', 'Formal eine Frage, aber Modalität <code>höflicher Wunsch</code> mit klarem Handlungskern → Sprechakt <code>COMMAND</code>.'),
      S('Abgrenzung', 'Entscheidend ist die Unterscheidung zum Hypothetischen: <code>„Wäre es möglich…“</code> ist ein Wunsch, <code>„Was wäre, wenn…“</code> ein Gedankenspiel.'),
      S('Semantisches Lexikon', 'Aktion <code>einschalten</code> · Eigenname <code>Küchenlicht</code>.'),
      S('Semantic Frame', 'action <code>turn_on</code> · target <code>Küchenlicht</code> — identisch zum Imperativ „Schalte das Küchenlicht ein.“'),
      S('Entity-Auflösung', 'Eindeutiger Treffer über den Friendly Name → <code>light.kueche</code>, Status <code>RESOLVED</code>.'),
      S('Capability-Prüfung', '<code>turn_on</code> wird vom Gerät gemeldet.'),
      S('Execution Policy', 'Risiko niedrig · ein Ziel · direkte Ausführung.')
    ],
    kind: 'plan', tagText: 'ServiceCallPlan', meta: 'ausgeführt',
    say: 'Alles klar, das Küchenlicht ist an.',
    plan: [['Dienst', 'light.turn_on'], ['Ziel', 'light.kueche'], ['Risiko', 'niedrig'], ['Identisch zu', '5 weiteren Formulierungen']],
    why: '<b>Kein Template-Matching:</b> „Schalte … ein“, „Kannst du … anmachen?“, „Ich hätte gerne … an“ und „Das … soll an sein“ führen über die Sprechakt-Analyse zum selben geprüften Frame — nicht über eine Liste vollständiger Sätze.'
  },
  {
    tag: 'Gedankenspiel — bleibt lesend',
    text: 'Was würde passieren, wenn ich jetzt alle Rollläden runterfahre?',
    stages: [
      S('Normalisierung', 'Konjunktiv und Konditional bleiben erhalten — sie sind das entscheidende Signal.'),
      S('Äußerungsanalyse', 'Sprechakt <code>QUERY</code> · Modalität <code>hypothetisch</code> · <code>safe_to_execute_directly = false</code>.'),
      S('Klauselrollen', 'Die <code>wenn</code>-Klausel ist eine Bedingung innerhalb einer Informationsfrage, kein auszuführender Hauptsatz.'),
      S('Sperre', 'Ein hypothetischer oder unsicherer Satz kann den Befehlspfad nicht betreten. Die Sperre greift vor jeder Entity-Auflösung.'),
      S('World Model', 'Vier Rollläden freigegeben — sie werden nur <b>gelesen</b>, um antworten zu können.'),
      S('Ergebnis', 'Beschreibung des hypothetischen Effekts, ohne dass ein Plan entsteht oder ausgeführt wird.')
    ],
    kind: 'stop', tagText: 'Keine Ausführung', meta: 'hypothetisch erkannt',
    say: 'Vier Rollläden würden geschlossen: Wohnzimmer, Küche, Bad und Schlafzimmer. Ich habe nichts verändert.',
    plan: [['Dienst', '— gesperrt —'], ['Sprechakt', 'QUERY'], ['Modalität', 'hypothetisch'], ['safe_to_execute_directly', 'false']],
    why: '<b>Das ist ausführungsrelevant:</b> Genau hier verunglücken generative Assistenten regelmäßig — sie beantworten ein Gedankenspiel, indem sie es ausführen. HomeIntent trennt beides schon auf Ebene der Satzart.'
  },
  {
    tag: 'Kritische Aktion',
    text: 'Entriegle die Haustür.',
    stages: [
      S('Normalisierung', 'Kanonisierung des Verbs <code>entriegeln</code>.'),
      S('Äußerungsanalyse', 'Sprechakt <code>COMMAND</code> · direkt · unmissverständlich.'),
      S('Semantic Frame', 'action <code>unlock</code> · target <code>Haustür</code>.'),
      S('Entity-Auflösung', 'Eindeutig → <code>lock.haustuer</code>, aktueller Zustand <code>locked</code>.'),
      S('Capability-Prüfung', 'Die Domäne <code>lock</code> unterstützt <code>unlock</code>.'),
      S('Risikobewertung', '<code>lock</code> steht auf der Hochrisiko-Liste; die Kombination <code>lock + unlock</code> wird ausdrücklich auf <b>KRITISCH</b> gehoben.'),
      S('Benutzerprüfung', 'Kritische Aktionen sind per Voreinstellung Administratoren vorbehalten; nur derselbe Benutzer darf die Bestätigung abschließen.'),
      S('Execution Policy', 'Der Plan wird erzeugt, aber <b>nicht ausgeführt</b>. Er wartet auf ein ausdrückliches Ja.')
    ],
    kind: 'confirm', tagText: 'Bestätigung nötig', meta: 'Plan hält an',
    say: 'Soll ich die Haustür wirklich entriegeln?',
    plan: [['Dienst', 'lock.unlock'], ['Ziel', 'lock.haustuer'], ['Risiko', 'KRITISCH'], ['Status', 'wartet auf Bestätigung'], ['Gültig', '120 s, benutzergebunden']],
    why: '<b>Die Risikostufe ist konfigurierbar</b>, aber die Zuordnung nicht beliebig: Alarmanlage und Entriegeln sind fest als kritisch hinterlegt. Mehr als fünf gleichzeitige Ziele heben jede Stufe zusätzlich um eine an.'
  },
  {
    tag: 'Automation per Sprache',
    text: 'Wenn es dunkel wird, mach die Stehlampe an.',
    stages: [
      S('Äußerungsanalyse', 'Sprechakt <code>AUTOMATION</code> — die <code>wenn</code>-Klausel trägt hier eine Auslöserrolle, keine hypothetische.'),
      S('Klauseltrennung', 'Auslöser: „es wird dunkel“ · Aktion: „Stehlampe an“ · keine zusätzliche Bedingung.'),
      S('Auslöser-Semantik', 'Sonnenstand-Auslöser <code>sun</code> mit Ereignis <code>sunset</code>.'),
      S('Aktions-Semantik', 'Die Aktion läuft durch <b>denselben</b> semantischen Compiler und dieselben Capability-Prüfungen wie ein direkter Befehl.'),
      S('AutomationModel', 'trigger <code>sun/sunset</code> · action <code>light.turn_on</code> · entity <code>light.wohnzimmer_stehlampe</code>'),
      S('AutomationValidator', 'Schema, Zielfähigkeit und Nur-Lesen-Richtlinie werden geprüft, bevor irgendetwas geschrieben wird.'),
      S('Vorschau', 'Der erzeugte YAML-Entwurf wird vorgelesen und muss bestätigt werden.'),
      S('Executor', 'Erst nach dem Ja: Schreiben in <code>automations.yaml</code>, Reload, Journaleintrag, Metadatenabgleich.')
    ],
    kind: 'confirm', tagText: 'Vorschau', meta: 'noch nichts geschrieben',
    say: 'Ich würde anlegen: Bei Sonnenuntergang die Stehlampe einschalten. Soll ich das speichern?',
    plan: [['Auslöser', 'sun · sunset'], ['Aktion', 'light.turn_on'], ['Ziel', 'light.wohnzimmer_stehlampe'], ['Kategorie', 'Homeintent'], ['Status', 'Entwurf, unbestätigt']],
    why: '<b>Erzeugte Automationen sind gewöhnliche HA-Automationen</b> in der Kategorie „Homeintent“ — sichtbar, editierbar und löschbar in der normalen Oberfläche. Ein CI-Job validiert das erzeugte Schema gegen ein echtes Home Assistant im Docker-Container.'
  },
  {
    tag: 'V7-Autorität — neu in 4.62',
    text: 'Mach das Küchenlicht auf 30 Prozent.',
    stages: [
      S('Loss-aware Frontend', 'Ein <code>LanguageDocument</code> hält Originaltokens, Quellspannen und Normalisierungsvarianten mit Kosten und Herkunft fest — der Rohtext wird nie überschrieben.'),
      S('SemanticInterpreter', 'Erzeugt vollständige <code>MeaningCandidates</code> und meldet offen, was fehlt: Konflikte, leere Slots, ungeklärte Tokens.'),
      S('Katalogabgleich', 'Das Paar <code>light</code> + Prozentwert steht in <code>semantic_catalog.py</code> auf der vermessenen Capability-Liste → V7 ist hier <b>autoritativ</b>.'),
      S('Score-Margin', 'Nur ein <b>vollständiger</b> Kandidat zählt. Zwei konkurrierende vollständige Lesarten bräuchten mindestens <code>10</code> Scorepunkte Abstand — hier gibt es nur eine.'),
      S('UnderstandingOutcome', 'Ergebnis <code>COMMAND</code> · <code>authority = V7</code>. Der Live-Router lässt den Treffer vor dem historischen Device-Router passieren.'),
      S('Revalidierung', 'Die stabile Entity-ID wird gegen den <b>aktuellen</b> Registry-Snapshot und die aktuelle Capability erneut geprüft — nicht gegen den Stand von vorhin.'),
      S('Shadow-Gate', 'Derselbe Turn läuft im Release-Vergleich rein lesend gegen den Legacy-Pfad. Bei 3.772 Turns: 0 Divergenzen.')
    ],
    kind: 'plan', tagText: 'ServiceCallPlan', meta: 'V7 autoritativ',
    say: 'Okay, das Küchenlicht steht auf 30 Prozent.',
    plan: [['Dienst', 'light.turn_on'], ['Ziel', 'light.kueche'], ['brightness_pct', '30'],
           ['authority', 'V7'], ['Risiko', 'niedrig']],
    why: '<b>Warum das eine eigene Stufe ist:</b> Bedeutung lag schon länger im Compiler — die <em>Entscheidung</em> traf aber oft noch ein gewachsener Spezialparser. Seit 4.60 ist die Reihenfolge umgedreht, und <code>authority</code> macht für jeden Turn nachprüfbar, welcher Pfad geantwortet hat. Nicht migrierte Fachcapabilities bleiben kontrollierter Fallback hinter derselben Sicherheitsgrenze.'
  }
];

const picker = $('#picker'), stagesEl = $('#stages'), demoText = $('#demoText'),
      verdict = $('#verdict'), verdictTag = $('#verdictTag'),
      verdictMeta = $('#verdictMeta'), verdictBody = $('#verdictBody');

let runToken = 0;

function buildPicker() {
  EXAMPLES.forEach((ex, i) => {
    const b = document.createElement('button');
    b.className = 'pick';
    b.type = 'button';
    b.setAttribute('role', 'tab');
    b.innerHTML = `<b>${ex.tag}</b>${ex.text}`;
    b.addEventListener('click', () => select(i));
    picker.append(b);
  });
}

async function select(i) {
  const ex = EXAMPLES[i];
  const token = ++runToken;

  $$('.pick', picker).forEach((p, n) => p.classList.toggle('on', n === i));
  picker.dataset.current = i;

  demoText.textContent = ex.text;
  verdict.dataset.kind = 'idle';
  verdictTag.textContent = 'verarbeitet …';
  verdictMeta.textContent = '';
  verdictBody.innerHTML = '<p class="muted">Die Pipeline läuft.</p>';

  stagesEl.innerHTML = '';
  const nodes = ex.stages.map(s => {
    const li = document.createElement('li');
    li.className = 'stage';
    li.innerHTML = `<span class="stage__dot"></span><div><div class="stage__t">${s.t}</div><div class="stage__v">${s.v}</div></div>`;
    stagesEl.append(li);
    return li;
  });

  await sleep(180);
  for (const li of nodes) {
    if (token !== runToken) return;
    li.classList.add('on');
    await sleep(330);
  }
  if (token !== runToken) return;

  await sleep(220);
  verdict.dataset.kind = ex.kind;
  verdictTag.textContent = ex.tagText;
  verdictMeta.textContent = ex.meta;
  verdictBody.innerHTML =
    `<p class="say">${ex.say}</p>` +
    `<div class="plan">${ex.plan.map(([k, v]) =>
      `<div class="plan__row"><span>${k}</span><b>${v}</b></div>`).join('')}</div>` +
    `<div class="why">${ex.why}</div>`;
}

if (picker) {
  buildPicker();
  $('#replay').addEventListener('click', () => select(+(picker.dataset.current || 0)));
  const demoIO = new IntersectionObserver((e, obs) => {
    if (!e[0].isIntersecting) return;
    obs.disconnect();
    select(0);
  }, { threshold: 0.2 });
  demoIO.observe($('#demo'));
}

/* ══════════════════════════════════════════════════════════
   Sprachhüllen
   ══════════════════════════════════════════════════════════ */
const PHRASES = [
  'Schalte das Küchenlicht ein.',
  'Kannst du das Küchenlicht anmachen?',
  'Wäre es möglich, das Küchenlicht einzuschalten?',
  'Ich hätte gerne das Küchenlicht an.',
  'Sorge bitte dafür, dass das Küchenlicht an ist.',
  'Das Küchenlicht soll an sein.'
];
const morphList = $('#morphList');
if (morphList) {
  PHRASES.forEach(p => {
    const d = document.createElement('div');
    d.className = 'morph__line';
    d.textContent = p;
    morphList.append(d);
  });
  const lines = $$('.morph__line', morphList);
  let mi = 0;
  const cycle = () => {
    lines.forEach((l, n) => l.classList.toggle('on', n === mi));
    mi = (mi + 1) % lines.length;
  };
  cycle();
  if (!reduced) setInterval(cycle, 1700);
}

/* ══════════════════════════════════════════════════════════
   Domänen
   ══════════════════════════════════════════════════════════ */
const DOMAINS = [
  ['light', 'ein/aus, umschalten, Helligkeit, Farbe, Farbtemperatur, relative Helligkeit'],
  ['switch', 'ein/aus und umschalten'],
  ['cover', 'öffnen, schließen, Position und Lamellenneigung'],
  ['fan', 'ein/aus, Prozent, Stufe, Preset, Richtung und Oszillation'],
  ['climate', 'Solltemperatur, HVAC-, Preset-, Lüfter- und Schwenkmodus'],
  ['media_player', 'Wiedergabe, Pause, Stopp, Lautstärke, Stummschalten und Quelle'],
  ['vacuum', 'starten, pausieren, stoppen, Saugstufe, Ladestation und Orten'],
  ['scene', 'aktivieren'],
  ['script', 'starten'],
  ['lock', 'verriegeln und bestätigtes Entriegeln'],
  ['humidifier', 'ein/aus, Zielfeuchte und angebotener Modus'],
  ['water_heater', 'Solltemperatur und angebotener Betriebsmodus'],
  ['select', 'tatsächlich angebotene Option auswählen'],
  ['number · input_number', 'Wert innerhalb der gemeldeten Grenzen setzen'],
  ['input_boolean', 'ein/aus und umschalten'],
  ['button', 'nach Bestätigung drücken'],
  ['valve', 'nach Bestätigung öffnen, schließen oder positionieren'],
  ['lawn_mower', 'starten, pausieren und zur Ladestation fahren'],
  ['camera', 'Stream auf einem eindeutig genannten Media Player anzeigen'],
  ['notify', 'Nachricht an ein eindeutig genanntes Notify-Ziel senden'],
  ['alarm_control_panel', 'bestätigte Alarmaktionen; kritische Aktionen nur für Admins'],
  ['group', 'explizit ausgewählte Gruppen nach Bestätigung steuern'],
  ['sensor · binary_sensor', 'Zustände, Messwerte und Vergleiche abfragen'],
  ['calendar', 'Termine lesen, anlegen und – je nach Integration – ändern oder löschen'],
  ['todo', 'Listen lesen und Einträge verwalten'],
  ['timer', 'starten, ändern, pausieren, fortsetzen, beenden und abfragen'],
  ['sun · weather', 'Sonnenauf- und -untergang, aktuelles Wetter und Vorhersage'],
  ['person', 'Anwesenheit abfragen — einzeln oder für den ganzen Haushalt']
];
const domainsEl = $('#domains');
if (domainsEl) {
  domainsEl.innerHTML = DOMAINS.map(([n, d]) =>
    `<div class="dom"><span class="dom__n">${n}</span><span class="dom__d">${d}</span></div>`).join('');
}

})();
