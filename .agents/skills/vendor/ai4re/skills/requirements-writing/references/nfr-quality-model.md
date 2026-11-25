# Non-Functional Requirements — Quality Model & Accessibility

> **Provenance:** `[Supplementary: ISO/IEC 25010:2023]` quality model; category 10
> *Randbedingungen* is a ReqPOOL convention (not part of ISO/IEC 25010).
> `[Supplementary: BMSGPK Vertragsbeilage B, Stand März 2022]` for the Austrian accessibility
> section. Standard versions change — confirm the version the tender/contract names.

## 1. Definition

A non-functional requirement (NFR) refers to a **quality characteristic** of the system that
functional requirements do not cover. It describes *how* the system operates (e.g. timing
behavior, usability), not *which tasks* it performs.

## 2. Classification — ISO/IEC 25010:2023 (+ Randbedingungen)

Assign every NFR to exactly **one** category and, where possible, one sub-characteristic.
Use the German labels in German-language catalogues.

| # | Category (DE / EN) | Sub-characteristics |
|---|--------------------|---------------------|
| 1 | Funktionale Eignung / Functional Suitability | Funktionale Vollständigkeit, Funktionale Korrektheit |
| 2 | Leistungseffizienz / Performance Efficiency | Zeitverhalten, Ressourcenverbrauch, Kapazität |
| 3 | Kompatibilität / Compatibility | Koexistenz, Interoperabilität |
| 4 | Interaktionsfähigkeit / Interaction Capability | Erlernbarkeit, Bedienbarkeit, Schutz vor Benutzerfehlern, Nutzerbindung, Inklusivität (Barrierefreiheit), Benutzerunterstützung, Selbstbeschreibungsfähigkeit |
| 5 | Zuverlässigkeit / Reliability | Fehlerfreiheit, Verfügbarkeit, Fehlertoleranz, Wiederherstellbarkeit |
| 6 | Sicherheit / Security | Vertraulichkeit, Integrität, Nachweisbarkeit, Authentizität, Widerstandsfähigkeit |
| 7 | Wartbarkeit / Maintainability | Modularität, Wiederverwendbarkeit, Analysierbarkeit, Änderbarkeit, Testbarkeit |
| 8 | Flexibilität / Flexibility | Anpassbarkeit, Skalierbarkeit, Installierbarkeit, Austauschbarkeit |
| 9 | Betriebssicherheit / Safety | Betriebliche Einschränkungen, Risikoidentifikation, Fail-Safe-Verhalten, Gefahrenwarnung, Sichere Integration |
| 10 | Randbedingungen / Constraints *(not ISO 25010)* | Produkt- & Prozessrandbedingungen: Support, vertragliche und organisatorische Vorgaben |

**Rules**
- Category 1 is rarely an NFR on its own — check whether the statement is really a
  functional requirement before filing it there.
- Accessibility belongs to **4 · Inklusivität (Barrierefreiheit)**; contractual proof
  obligations about accessibility (test report, statement, contact person) belong to
  **10 · Randbedingungen**.
- Support language, SLAs, delivery formats, signatures, staffing → **10**.
- In decompositions, walk all ten categories; every one is either covered or explicitly
  marked *not relevant* with a one-line reason.

**Examples**
- *Inklusivität:* „Das System SOLL die von ihm erzeugten PDF-Ausgaben barrierefrei
  bereitstellen."
- *Randbedingungen:* „Der Anbieter MUSS den Support in deutscher Sprache erbringen."
- *Zeitverhalten:* „Das System MUSS Suchergebnisse bei bis zu 200 gleichzeitigen Nutzer:innen
  innerhalb von 2 Sekunden (95. Perzentil) anzeigen."

## 3. Accessibility in Austrian public-sector catalogues

In Austrian public-sector requirement catalogues, accessibility (*Barrierefreiheit*) is a
mandatory NFR block, not an optional extra. Always propose it when the system has a user
interface, produces documents, or embeds media — even if the input does not mention it.

### 3.1 Legal and normative basis

| Basis | Content |
|-------|---------|
| **WZG** (Web-Zugänglichkeitsgesetz) | Austrian implementation of EU Directive 2016/2102; applies to websites and mobile apps of the federal government and public bodies |
| **WCAG** in the current version, level **AA** | Beilage B (2022) names WCAG 2.1 AA; the contract text says "jeweils aktuelle Fassung" → confirm whether WCAG 2.2 is required |
| **EN 301 549** (Beilage B: V3.2.1, 2021-03) | Harmonised EU standard; references all WCAG 2.1 AA success criteria and adds further criteria |
| **ATAG** | W3C guidelines for authoring tools (CMS / editorial system) |
| **UAAG** | W3C guidelines for user agents (e.g. video players) |
| **BEinstG** | Anti-discrimination for employees with disabilities → relevant for back-office/editorial UIs |
| `[Supplementary]` **BaFG** (Barrierefreiheitsgesetz, since 28 June 2025) | Austrian implementation of the European Accessibility Act for products/services of private economic operators — check applicability |

### 3.2 EN 301 549 clauses beyond WCAG — when they apply

| Clause | Applies when the system … |
|--------|---------------------------|
| 5 — Generic | uses biometrics for identification or control |
| 6 — ICT with two-way voice communication | offers real-time communication (e.g. video conferencing) |
| 7 — Video capabilities | presents video, contains a video player or video files |
| 9 — Web | is a website / contains web content (= WCAG 2.1 AA) |
| 10 — Non-web documents | provides downloadable documents or forms (PDF, Office) |
| 11 — Software | is a web app/app; also authoring tools (CMS) and user agents (players) |
| 12 — Documentation and support services | ships product documentation or offers support |

### 3.3 Typical requirement topics (from Vertragsbeilage B)

Write each as a separate, self-contained requirement. Category in brackets.

**Product (4 · Inklusivität)**
- Design, content, operation and technical implementation conform to WCAG AA and the
  applicable EN 301 549 clauses.
- CMS/editorial system: its own UI conforms to WCAG 2.1 AA **and** supports editors in
  creating accessible content (EN 301 549 clause 11, ATAG).
- W3C web technologies (HTML, CSS, WAI-ARIA, SVG, SMIL) are used specification-conform.
- Design deliverables can be implemented accessibly with W3C web technologies.
- Texts are easy to understand and appropriate for the defined target groups.
- Security measures (e.g. CAPTCHA, session timeouts) do not create accessibility barriers.

**Process & contract (10 · Randbedingungen)**
- Offer names a contact person for digital accessibility and proves accessibility
  competence (qualification + experience) of at least one project-team member.
- Offer justifies the accessibility conformance of any proprietary (non-W3C) technology.
- Contractor follows the "Corporate Design – Webseiten des Bundes" style guide unless
  agreed otherwise.
- Contractor reports deviations from WCAG / EN 301 549 to the client's contact person as
  early as possible, with a problem description and an equivalent alternative solution.
- Contractor reports barriers found in the CMS or other tools immediately.
- On delivery: written confirmation of accessibility conformance + self-assessment report
  (WCAG 2.1 AA incl. sufficient techniques, failures and advisory techniques for levels
  A/AA, plus applicable EN 301 549 criteria). Signature by a certified accessibility expert
  (e.g. CWAE, IAAP CPACC/WAS/CPWA/ADS) is recommended.
- Test reports from the W3C WCAG-EM Report Tool are delivered as HTML **and** JSON.
- Contractor details all non-conformities for the accessibility statement and contributes to
  its creation (mandatory per WZG from go-live).
- Contractor fixes accessibility defects within an agreed period **at no extra cost**,
  repeats the test for corrected elements and updates the confirmation and the statement.
- Contractor cooperates in a certification audit if planned (e.g. WACA Gold) and fixes audit
  findings at no extra cost within the audit period.
- Accompanying documentation is delivered as accessible PDF plus source file.

**Related annexes (do not merge — reference the standard, not another requirement)**
- Beilage A — accessible publications/documents (PDF)
- Beilage D1 / D2 — ÖGS (Austrian sign language) videos / live interpretation
- Beilage E — minimum requirements for easy-to-read language (*leicht verständliche Sprache*)

### 3.4 Verification hints (client acceptance)

Acceptance typically samples: W3C HTML and CSS validators, colour-contrast tools, automated
WCAG test tools, browser plugins (e.g. Lighthouse), manual keyboard tests, screen-reader
tests (possibly with users of assistive technologies), and manual EN 301 549 test steps.
Use these as the verification method for the corresponding requirements.

### 3.5 Sources

- WCAG 2.1: https://www.w3.org/TR/WCAG21/ · How to meet WCAG: https://www.w3.org/WAI/WCAG21/quickref/
- EN 301 549 V3.2.1: https://www.etsi.org/deliver/etsi_en/301500_301599/301549/03.02.01_60/en_301549v030201p.pdf
- FFG criteria catalogue: https://www.ffg.at/digitale-barrierefreiheit/digitales-zugaenglich-machen/kriterienkatalog-web
- Verwaltungswiki Portal:Barrierefrei: https://www.ag.bka.gv.at/at.gv.bka.wiki-bka/index.php/Portal:Barrierefrei
- WCAG-EM Report Tool: https://www.w3.org/WAI/test-evaluate/conformance/
