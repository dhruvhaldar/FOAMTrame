# FOAMTrame enhancement implementation roadmap

Last reviewed: **2026-09-24**  
Implementation baseline: **`5a3ba76`**, branch `dev`  
Purpose: track delivered enhancements, phase the remaining work, and provide a
maintainable register for future additions.

## Scope and status conventions

The product direction is a guided CFD workspace covering case creation/import,
geometry, meshing, physics, execution, analysis, and reporting. Rival screenshots
are design references; they are not evidence that a feature exists in FOAMTrame.

This snapshot is based on the checked-out implementation, README, and regression
tests. **Implemented** means present within the stated scope; it does not imply
support for every OpenFOAM solver, geometry, or runtime. Tests were not rerun for
this documentation update. The previous implementation handoff recorded 175 tests
passed, 2 skipped, and passing Ruff and type checks.

| Status | Meaning |
| --- | --- |
| Implemented | Available in the current source within its documented scope. |
| Partial | A working foundation exists, but the phase's proposed outcome needs more work. |
| Proposed | Recommended future work; not scheduled or approved for implementation. |
| Planned | Approved scope with agreed acceptance criteria; work has not started. |
| In progress | Implementation is actively underway. |
| Blocked | A named dependency prevents progress; record the unblock condition. |
| Deferred | Intentionally postponed, with a reason and revisit condition. |

Future phases require user approval before implementation, following the existing
phase-by-phase review approach. Adding an idea here does not authorize its build.
Phase numbers describe the proposed delivery sequence, not new UI tabs or release
versions. Dependencies can require a supporting item from a later phase first.

## Priority levels

| Priority | Meaning | Scheduling rule |
| --- | --- | --- |
| P0 — Critical | Data integrity, unusable core workflows, crashes, or incorrect case generation | Address confirmed defects before new features. |
| P1 — High | Essential workflow completeness and confidence in simulation results | Next enhancement cycle after approval. |
| P2 — Medium | Deeper engineering controls, reproducibility, and productivity | Follow P1; order by dependency and user need. |
| P3 — Future | Wider solver scope, scale, and optional automation | Scope separately after the core workflow is validated. |

Priorities below are recommendations, not delivery dates. Implemented items
retain their phase's priority as a maintenance priority; they are not pending work.
Every item inherits its phase priority unless the ranked backlog overrides it.
No new P0 defect is asserted by this documentation review.

## Phase overview

| Phase | Outcome | Status | Priority | Dependency |
| --- | --- | --- | --- | --- |
| 1 | Stable workspace and case management | Implemented | P1; P0 for critical regressions | Foundation for later phases |
| 2 | Guided meshing and quality inspection | Implemented — initial scope | P1 | Core meshing workflow delivered |
| 3 | Physics and boundary authoring | Implemented — initial scope | P1 | Named mesh patches |
| 4 | Unified readiness and simulation monitoring | Partial | P1 — next | Phases 2–3 |
| 5 | Advanced mesh controls and mesh studies | Proposed | P2 | Phase 2; phase 4 for studies |
| 6 | Reproducible analysis and engineering reports | Partial | P2 | Existing Plots/Post; phase 4 |
| 7 | Project library and design comparisons | Partial | P2 | Existing case operations |
| 8 | Broader physics and controlled automation | Proposed | P3 | Validated core workflow |

## Ranked next-enhancement backlog

All entries below are **Proposed** and await approval. Completed capabilities
remain in the phase inventories, rather than appearing as unfinished backlog.

| Rank | IDs | Priority | Next deliverable | Reason for order |
| --- | --- | --- | --- | --- |
| 1 | RUN-04 | P1 | Unified case-readiness summary with actionable missing prerequisites | Connects the delivered workspaces into a guided workflow. |
| 2 | RUN-05, RUN-06 | P1 | Engineering monitors and evidence-based convergence reporting | Helps assess solution quality beyond process completion. |
| 3 | ADV-MESH-01, ADV-MESH-02, ADV-MESH-04 | P2 | Local refinement, explicit domain controls, and mesh inspection tools | Improves control over the mesh used by the solver. |
| 4 | ADV-MESH-03 | P2 | Advanced layer controls and documented y+ estimates | Builds on mesh controls and physical setup. |
| 5 | POST-03, POST-05 | P2 | Saved views and reusable engineering measurements | Makes analysis repeatable and supports later comparisons. |
| 6 | CASE-04, ADV-MESH-05, POST-04 | P2 | Preserved variants, mesh studies, and linked result comparison | Depends on monitoring, repeatable analysis, and variant identity. |
| 7 | POST-06 | P2 | Exportable engineering report with source evidence | Assembles validated setup and analysis results. |
| 8 | CASE-02, CASE-03 | P2 | Project cards/search and in-app trash restore | Improves management of a growing case library. |
| 9 | CASE-05 | P3 — override | Reviewed parameter sweeps through the queue | Requires variant tracking and comparable outputs first. |
| 10 | FUT-01 through FUT-05 | P3 | Individually scoped physics, templates, and automation extensions | Expands scope after the core workflow is established. |

Reorder this backlog when a confirmed defect, dependency, or user priority changes;
record the reason in the change history.

## Phase 1 — Stable workspace and case management

**Status: Implemented.** Establish a reliable local workspace and reusable
execution/persistence services.

| ID | Enhancement | Status |
| --- | --- | --- |
| CORE-01 | Create blank cases, discover/import tutorials, select the active case | Implemented |
| CORE-02 | Copy and rename cases; confirmed deletion into recoverable workspace trash | Implemented |
| CORE-03 | Reject case-name collisions, path redirects, and operations on queued/running cases | Implemented |
| CORE-04 | SQLite operational state, portable backup, and deep case backup | Implemented |
| CORE-05 | Server-side remote VTK views and application-log diagnostics instead of a native output window | Implemented |
| CORE-06 | Responsive glass UI, bundled assets, documentation, and runtime diagnostics | Implemented |

Case deletion recovery currently uses a manual folder move followed by Refresh
List. An in-app restore action belongs to phase 7.

Evidence: [Setup](tabs/setup_tab.py), [case operations](backend/case/operations.py),
[persistence](app_state.py), [case-operation tests](tests/integration/test_case_operations.py),
and [VTK regressions](tests/integration/test_vtk_runtime.py).

## Phase 2 — Guided meshing and quality inspection

**Status: Implemented within the initial closed STL/OBJ workflow.**

| ID | Enhancement | Status |
| --- | --- | --- |
| MESH-01 | Dedicated Meshing workspace and inspection of existing `constant/polyMesh` | Implemented |
| MESH-02 | Surface selection, padded domain preview, base fineness, surface refinement, and layer count | Implemented |
| MESH-03 | Review generated dictionaries, back up originals, and submit fixed meshing actions through the FIFO queue | Implemented |
| MESH-04 | Queued/running viewer state, completion refresh, and failure/cancellation feedback | Implemented |
| MESH-05 | `checkMesh` execution and a compact detailed-report dialog with unchanged supporting log text | Implemented |
| MESH-06 | Preserve warnings on an overall pass; distinguish explicit verdicts from reported metrics | Implemented |
| MESH-07 | Per-patch visibility and transparency, all visible/opaque by default, preserving the camera | Implemented |
| MESH-08 | Version-aware generated dictionaries for Foundation and OpenCFD families | Implemented |

The initial workflow does not constitute advanced local refinement, mesh
independence analysis, or arbitrary CAD repair. Those are separate enhancements.

Evidence: [Meshing UI](tabs/meshing_tab.py),
[dictionary generation](backend/meshing/configuration.py),
[inspection/report parsing](backend/meshing/inspection.py),
[configuration tests](tests/integration/test_mesh_configuration.py),
[inspection tests](tests/integration/test_mesh_inspection.py), and
[progress tests](tests/integration/test_meshing_progress.py).

## Phase 3 — Physics and boundary setup

**Status: Implemented for single-region, constant-viscosity incompressible flow.**

| ID | Enhancement | Status |
| --- | --- | --- |
| PHYS-01 | Physics tab linked from Setup and driven by the active case's named mesh patches | Implemented |
| PHYS-02 | Steady/transient flow, laminar/kOmegaSST, viscosity, initial fields, and time/output controls | Implemented |
| PHYS-03 | Patch highlighting and compatible inlet, outlet, wall, slip, symmetry, and empty assignments | Implemented |
| PHYS-04 | Exact file-change preview, backup, rollback, and stale-file/mesh revalidation on save | Implemented |
| PHYS-05 | Foundation 12/13 and OpenCFD vXXXX dictionary families | Implemented |
| PHYS-06 | Reload supported saved values; reject unsupported solver families and includes/macros without rewriting them | Implemented |

### How Physics fits different case sources

| Case source | Intended behavior |
| --- | --- |
| Create New Case | Create → Geometry → Meshing → Physics → Run/Log. A complete mesh supplies the boundary names. |
| Imported tutorial | Retain the tutorial's case files and authored workflow. Edit through Physics only when its solver and dictionary syntax fall within the supported scope. |
| Existing selected case | Inspect its mesh and load supported settings; review exact changes before saving. Unsupported cases remain available to the other workspaces. |

Pressure is kinematic pressure (`p/rho`, m²/s²). Saving is explicit and does not
launch a solver. Compressible, thermal, multiphase, multi-region, cyclic/wedge,
and non-uniform-field authoring remain outside this phase.

Evidence: [Physics service](backend/physics.py), [Physics UI](tabs/physics_tab.py),
and [authoring regressions](tests/integration/test_physics.py).

## Phase 4 — Unified readiness and simulation monitoring

**Status: Partial. Recommended next phase, subject to approval.** Existing
execution and logging work; the next addition should help users judge whether a
case is ready and whether its solution is credible.

| ID | Enhancement | Status |
| --- | --- | --- |
| RUN-01 | Capability-based actions, unavailable reasons, FIFO queue, cancellation, and run history | Implemented |
| RUN-02 | Console copy, scroll-to-top/bottom, and default following that pauses during manual review | Implemented |
| RUN-03 | Preserve case-owned logs and identify complete/partial `Allrun` skips | Implemented |
| RUN-04 | Unified readiness summary across geometry, mesh, physics, runtime, and action prerequisites | Proposed |
| RUN-05 | Configurable residual and engineering monitors, including mass balance and applicable forces/pressure drop | Proposed |
| RUN-06 | Distinguish process completion from numerical convergence; provide links to supporting evidence | Proposed |

Implementation approach: aggregate existing validators rather than create a second
execution path. Add monitor parsing and configuration through shared backend
services. Treat convergence criteria as case-specific settings.

Acceptance: a supported new case can reach a reviewable ready state; missing
prerequisites link to the relevant workspace; a successful process exit alone
never earns a convergence verdict; manual console scrolling remains stable.

Evidence for existing scope: [capabilities](backend/case/capabilities.py),
[queue](backend/simulation_queue.py), [Run/Log](tabs/run_log_tab.py), and
[queue tests](tests/integration/test_simulation_queue.py).

## Phase 5 — Advanced meshing and mesh studies

**Status: Proposed.** Extend the delivered meshing workflow in bounded steps.

| ID | Enhancement | Status |
| --- | --- | --- |
| ADV-MESH-01 | Named surface/region refinements with viewer selection and visible refinement bounds | Proposed |
| ADV-MESH-02 | Explicit domain dimensions and asymmetric upstream/downstream padding | Proposed |
| ADV-MESH-03 | Layer thickness, growth controls, and a documented y+ estimation aid | Proposed |
| ADV-MESH-04 | Mesh section planes and highlighting of poor-quality entities when corresponding data is available | Proposed |
| ADV-MESH-05 | Named mesh variants and mesh-independence comparison against selected engineering quantities | Proposed |

Dependencies: phase 2; phase 4 monitoring for mesh-study quantities. Extend
`backend/meshing/` and the existing reviewed dictionary plan. Use preserved variants
or copied cases rather than silently replacing an existing mesh.

Acceptance: controls round-trip through reviewed files for supported runtimes;
quality overlays identify their data source; comparisons show mesh size, monitored
quantity, relative change, and assumptions. Estimated y+ is not presented as a
solved wall-field measurement.

## Phase 6 — Reproducible analysis and engineering reports

**Status: Partial.** Existing visualization should grow into repeatable analysis.

| ID | Enhancement | Status |
| --- | --- | --- |
| POST-01 | Live/cached plots, residual discovery, plot styling, maximization, and PNG export | Implemented |
| POST-02 | Server-side result visualization with slice, clip, and streamline controls | Implemented |
| POST-03 | Named saved views containing camera, field, range, filters, and time selection | Proposed |
| POST-04 | Linked result comparison with synchronized cameras and explicit shared color ranges | Proposed |
| POST-05 | Point/line probes and reusable surface-integral measurements | Proposed |
| POST-06 | Exportable engineering report with setup, mesh quality, monitors, figures, and run provenance | Proposed |

Dependencies: phase 4 for monitor/convergence evidence; phase 7 for organized
variant comparisons. Extend the existing Post/Plots services and add a report
service that consumes their data rather than scraping UI text.

Acceptance: saved views reproduce the same selection; comparisons disclose units,
times, and ranges; exported reports identify the case, runtime, settings, and
source run; missing evidence is labelled unavailable.

Evidence: [Post UI](tabs/visualizer_tab.py), [Plots UI](tabs/plots_tab.py),
[plot services](backend/plots/realtime_plots.py), and
[plot regressions](tests/integration/test_realtime_plots.py).

## Phase 7 — Project library and design comparisons

**Status: Partial.** Safe case operations exist; richer organization is proposed.

| ID | Enhancement | Status |
| --- | --- | --- |
| CASE-01 | Active-case selection and safe copy/rename/recoverable delete | Implemented |
| CASE-02 | Searchable project cards with thumbnails, tags, and meaningful workflow state | Proposed |
| CASE-03 | In-app trash listing and restore with collision checks | Proposed |
| CASE-04 | Case variants with recorded parentage and comparable input summaries | Proposed |
| CASE-05 | Parameter sweeps submitted through the existing queue with explicit resource/output estimates | Proposed |

Implementation approach: keep large datasets in case directories. Add only
necessary operational metadata to SQLite, with migrations and backup normalization.
Retain case locking and path validation for every management operation.

Acceptance: library metadata survives backup/restore; copy and restore cannot
overwrite cases; every comparison identifies its source variants; sweeps can be
reviewed and cancelled without modifying running cases.

## Phase 8 — Broader physics and controlled automation

**Status: Proposed.** Select individual extensions only after the core workflow
has representative validated examples.

| ID | Enhancement | Status |
| --- | --- | --- |
| FUT-01 | Additional turbulence and boundary-condition models | Proposed |
| FUT-02 | Thermal/compressible flow authoring | Proposed |
| FUT-03 | Multiphase and multi-region workflows | Proposed |
| FUT-04 | Typed automation/API actions and optional assisted setup | Proposed |
| FUT-05 | Reusable validated case templates and solver/runtime compatibility catalog | Proposed |

Each physics family needs its own file schema, units, compatibility checks, and
reference-case validation. Automation must reuse the same reviewed services,
fixed action IDs, queue, and destructive-action safeguards as the UI.

Acceptance: every supported family has documented limits and runtime validation;
unsupported input is preserved with an actionable explanation; no assisted action
can bypass the case-write review or submit arbitrary shell commands.

## Implementation and verification rules for every phase

1. Agree on a bounded outcome and acceptance criteria before moving Proposed to Planned.
2. Inspect the active implementation and relevant tests; preserve existing case data.
3. Implement reusable backend behavior, then connect the Trame UI to it.
4. Keep OpenFOAM dictionaries authoritative for physical case configuration; use
   SQLite for operational metadata and maintain backup compatibility.
5. Add meaningful regressions and run the repository-required Ruff gates plus
   relevant tests. Cross-cutting changes require the complete test suite.
6. Verify UI changes at desktop and constrained widths, including empty/error states.
7. Record exact validation results and limitations. Review the completed phase
   with the user before beginning the next proposed phase.

## Future enhancement record template

Append new entries with stable IDs; do not renumber delivered items. If a delivered
feature needs additional scope, create a new linked entry so its history remains
clear. Update both its detailed record and the phase overview when status changes.

```markdown
### ENH-XXX — Enhancement title

- Phase / priority:
- Status: Proposed
- User outcome:
- Scope:
- Explicit exclusions:
- Dependencies / related IDs:
- Backend and UI extension points:
- Persistence / backup / OpenFOAM compatibility impact:
- Acceptance criteria:
- Verification commands and results:
- Evidence: implementation, tests, commit or PR
- Known limitations / blocker and unblock condition:
- Approval / review date:
- Last updated:
```

## Change history

| Date | Change | Evidence |
| --- | --- | --- |
| 2026-09-24 | Established phased implementation inventory and future enhancement register | Source reviewed at `5a3ba76`; no new application features added |
