# Memory platform graph projection

`platform_graph.py` owns the read-only local-operator projection of current formal knowledge. `models.py` defines the two explicit HTTP response contracts; callers use `memory_graph_service.py` as the stable facade.

The source of truth remains Team Knowledge's existing owner stores and lifecycle eligibility. The projection does not create a graph store, change Agent ACL, impersonate owners, read file-backed private memories, expose source or item bodies, or include pending proposals and raw conversations.

The platform endpoint requires a server-bound privileged local operator and rejects Agent session headers. Topic grouping records its basis: reviewed research domain, sorted first tag, then owner-scoped knowledge base. Shared sources and research references retain multiple topic memberships; grouping and display proximity are not semantic support. Existing reviewed research relations retain their recorded direction; unknown relations remain candidates.

Overview and node-detail responses carry true counts, limits and truncation. Source location, hash, revision and review metadata are projected through the existing sanitizers. The current implementation scans the canonical store per request; pagination and large-platform profiling are future work, not verified by the first implementation.
