# Memory platform graph projection

`platform_graph.py` owns the read-only local-operator projection of current formal knowledge. `models.py` defines the two explicit HTTP response contracts; callers use `memory_graph_service.py` as the stable facade.

The source of truth remains Team Knowledge's existing owner stores and lifecycle eligibility. The projection does not create a graph store, change Agent ACL, impersonate owners, read file-backed private memories, expose source or item bodies, or include pending proposals and raw conversations.

The platform endpoint requires a server-bound privileged local operator and rejects Agent session headers. `display_names.py` chooses readable labels from reviewed research domains, semantic tags, explicit title keyword groups, then owner-scoped knowledge bases. Machine IDs, batch codes and workflow enums are not reading topics. Title keyword grouping is marked `title_keywords` and is display-only; canonical records are never changed. Missing document titles are identified explicitly rather than inferred. Research references use their own title when available, otherwise a Chinese record kind with the associated knowledge title only as context. Shared sources and research references retain multiple topic memberships; grouping and display proximity are not semantic support. Existing reviewed research relations retain their recorded direction; unknown relations remain candidates.

The platform UI excludes topic membership from content relationships and hides ingestion audit relations by default. The evidence view can opt into audit records. An absence of content relations is shown explicitly; no links are invented to fill the galaxy. Technical IDs and hashes remain available in collapsed details.

Overview and node-detail responses carry true counts, limits and truncation. Source location, hash, revision and review metadata are projected through the existing sanitizers. The current implementation scans the canonical store per request; pagination and large-platform profiling are future work, not verified by the first implementation.
