# Where should green energy investment go next? I built a tool to find out

Britain is putting £22 billion into electricity distribution infrastructure under RIIO-ED2, the price control framework that governs how DNOs (Distribution Network Operators) spend over the next five years. That's a lot of capital looking for a destination. The question nobody seems to have a straight answer to is: which of the 14 DNO licence areas in Great Britain should actually get priority?

The data to answer that question exists. It's just scattered across five different places — Ofgem's RIIO-ED2 performance data, NESO's constraint and carbon intensity feeds, ONS demographic and deprivation statistics, DESNZ energy statistics, and a pile of PDFs each DNO publishes independently about their own network. Nobody has pulled these into one place and scored the zones against each other on a like-for-like basis.

That gap matters to three different groups for three different reasons. A renewable developer trying to decide where to site a new solar or wind project needs to know which zones have spare grid capacity and which are queued up for years. An investor allocating capital across regional energy infrastructure needs a comparison they can actually defend to a committee. A policymaker trying to direct public money toward a just transition needs to know which zones combine grid readiness with genuine social need, not just whichever DNO shouts loudest in a consultation response.

Right now, each of those people is doing their own ad hoc version of this analysis — pulling a few spreadsheets, eyeballing a map, and making a judgment call. I wanted to see if I could build something that does it properly: pull the public data together, score every zone the same way, and make the weighting behind those scores something you can see and argue with rather than something buried in a consultant's black box.

---

The approach I landed on is a form of multi-criteria decision analysis, or MCDA — a fancy name for a fairly simple idea. You pick the things that matter for a decision, score every option against each of them, and combine those scores into one number you can rank by. I used five dimensions: renewable headroom, grid constraint severity, demand growth, socioeconomic vulnerability, and carbon intensity.

Renewable headroom comes from Ofgem's RIIO-ED2 data, specifically time-to-connect figures for low-voltage substations — a shorter wait means less queue pressure and more room to connect new generation. Grid constraint severity uses NESO's transmission boundary data, where a lower constraint limit means a more congested boundary. Demand growth is EV adoption rates pulled from DfT registration data, on the logic that fast-growing EV uptake is a leading indicator of network strain and future reinforcement need. Socioeconomic vulnerability is the Index of Multiple Deprivation (IMD 2019), population-weighted and aggregated up from local authority level to DNO zone level. Carbon intensity comes straight from NESO's Carbon Intensity API.

Each dimension gets normalised to a 0–1 scale using min-max scaling, so a zone's score reflects where it sits relative to the other 13, not some arbitrary absolute threshold. For dimensions where a lower raw number is actually better — like constraint severity — the normalisation is inverted so the scale still reads "higher is more investable" across the board. Then the five scores get combined with a weighted sum: multiply each dimension by a weight, add them up, and that's your composite score per zone.

I deliberately didn't reach for anything more sophisticated — no TOPSIS, no AHP, no fuzzy logic layers. Those methods exist and they're not wrong, but they trade transparency for nuance you don't necessarily need. The whole point of this tool is that a policymaker or an investor can look at the weights, disagree with them, change them, and see exactly how the rankings respond. A weighted sum is something you can explain in one sentence. A black-box AHP pairwise comparison matrix is not.

![Five public data sources flowing into the WADD scoring engine](screenshots/methodology_diagram.png)
*The five data sources — Ofgem, NESO, DfT, IMD 2019, and NESO's Carbon Intensity API — each feed one normalised dimension into the scoring engine.*

---

The build itself splits into three layers. At the bottom, a set of Python pipeline scripts each pull and clean one dimension — parsing Ofgem's RIIO-ED2 supplementary XLSM, hitting NESO's CKAN API for constraint data, working through a DfT ODS file for EV registrations, joining IMD scores up from local authority to DNO level, and grabbing a live snapshot from the Carbon Intensity API. Each script writes out a clean CSV with a normalised score per zone.

Above that sits a Flask backend that merges the five CSVs and exposes a scoring API. The key endpoint takes five weight parameters as a query string, computes the weighted composite for all 14 zones on the fly, and returns them ranked. There's also an endpoint that serves up the three preset scenarios and one that returns the full methodology as structured JSON, so the reasoning behind the scores is queryable, not just the scores themselves.

On top is a React frontend with five weight sliders, one per dimension, plus a ranked bar chart and a panel that breaks each zone's score down by dimension so you can see why it landed where it did. Move a slider and the rankings update within a few hundred milliseconds. The sliders auto-normalise — push one up and the other four proportionally shrink to keep everything summing to 100%, so you're always looking at a valid weighting rather than fighting the UI to make the numbers add up.

There are also three preset scenarios baked in: Equal Weights, which treats all five dimensions the same as a neutral baseline; Investor-Focused, which leans heavily on headroom, constraint severity, and demand growth because that's what a commercial developer actually cares about; and Just Transition, which puts the most weight on socioeconomic vulnerability. They exist because most people don't want to fiddle with five sliders from scratch — they want to see "what does this look like from an investor's chair" versus "what does this look like from a policy chair" with one click.

![Full app interface showing weight sliders, ranked bar chart, and the dimension breakdown panel](screenshots/app_full_screenshot.png)
*The three panels: weights on the left, the ranked bar chart in the centre, dimension breakdown on the right.*

---

Here's the part that actually matters. Under both Equal Weights and Just Transition, SP Manweb — Merseyside and North Wales — comes out on top. It scores a perfect 1.0 on both demand growth and socioeconomic vulnerability, and its headroom, constraint, and carbon intensity scores are all solidly mid-range rather than weak. That combination is hard to beat under almost any reasonable weighting, because it isn't relying on one standout number to carry the whole score.

Switch to Investor-Focused weights and the picture changes. NGED South Wales jumps to first place, driven by the highest carbon intensity score of any zone (a full 1.0) combined with one of the strongest constraint severity scores in the dataset. Under that lens, abatement potential and grid congestion matter more than who lives nearby, and South Wales wins on exactly those terms.

Scottish Hydro is the most interesting mover in the whole dataset. It sits 12th under Equal Weights, climbs to 5th under Investor-Focused because it has the single highest renewable headroom score of any zone in Great Britain, and then drops all the way to 13th under Just Transition because its socioeconomic vulnerability score is the lowest possible. Three completely different positions for the same zone, depending entirely on which values you bring to the table.

That's really the headline finding: zones like SP Manweb that hold a strong rank across every scenario are the safe bets — they're investable almost regardless of whose money it is or what that money is trying to achieve. Zones like Scottish Hydro, that swing from top-five to bottom-two depending on the weighting, are where the actual policy argument lives. Whether you fund that zone isn't a data question anymore at that point; it's a values question, and now at least you can see it as one.

![Same app, two different slider positions showing how rankings shift between scenarios](screenshots/scenario_comparison.png)
*Scottish Hydro's rank under Investor-Focused weights (left) versus Just Transition weights (right) — same data, opposite conclusions.*

---

I'd rather flag the weak points myself than have someone else find them. The biggest one is that Scotland and Wales deprivation data isn't harmonised with England's IMD framework yet, so three zones — Scottish Hydro, SP Distribution, and NGED South Wales — currently show a conservative zero on the vulnerability dimension with a flag in the data marking it as pending rather than measured. Until that's fixed, any ranking involving those three zones on the Just Transition end of the spectrum should be read with that caveat front and centre.

The headroom dimension is also an indirect proxy — I'm using time-to-connect figures from regulatory filings rather than actual queue volumes or live capacity data, because that's what's published in open, machine-readable form. It's the best available signal, not a perfect one. The whole model is also static: it scores each zone at a point in time rather than tracking how headroom, demand, or constraints are trending, and DNO licence areas themselves are a coarse unit that smooths over real variation within each zone.

The natural next steps follow from those gaps directly: pushing the analysis down to primary substation level instead of whole DNO zones, turning this into a time series instead of a single snapshot, pulling in connection queue data as it becomes available in more granular form, and potentially exposing the scoring API publicly so other people can build on top of it rather than re-deriving it themselves.

![Rankings panel zoomed in on the D4 data-pending flags for Scotland and Wales](screenshots/data_gap_callout.png)
*The three zones flagged as pending Scotland/Wales deprivation harmonisation — read their Just Transition rank with that caveat in mind.*

---

I work in electricity distribution engineering, and I'm in the middle of moving toward green energy finance. This project sits right at that join. The domain knowledge about how DNOs actually operate, what RIIO-ED2 measures, and where the real bottlenecks in the network sit came from inside the industry — and I wanted to prove that knowledge could be turned into something an investor or a civil servant could actually use, not just something useful to other engineers.

The methodology is documented in full, the code is public, and every single data point traces back to a government or regulator source — nothing in here is proprietary or scraped from somewhere it shouldn't be. If you want to poke at the weights yourself, disagree with the rankings, or build on top of it, the repo is here: [github.com/jaagboke/green-investment-tool](https://github.com/jaagboke/green-investment-tool).
