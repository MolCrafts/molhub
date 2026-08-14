# MolNex ETL tombstone — molix-data-dissolution

MolNex deleted its data-acquisition layer on 2026-08-14, branch
`feat/mm-param-val`, commit **6d425f7**
("refactor(molix)!: dissolve data/ phase 4 — ETL layer exits MolNex").
Phases 01-03 (eeed814, 9d69ebd, 30d1c61) rehomed the training-side
survivors first. Reference implementation for everything below = molnex
git history at 6d425f7^.

## Deleted files and verdicts

| deleted (molnex) | verdict |
|---|---|
| src/molix/data/source.py (DataSource, Sample, InMemorySource, SubsetSource) | dropped — superseded by molhub @dataset+load() protocol |
| src/molix/data/pipeline.py (Node, Edge, DAGCache, PipelineSpec, Pipeline) | superseded by streaming-data-tiers-03-conveyor (molhub) |
| src/molix/data/task.py (Runnable, Task, SampleTask, DatasetTask) | dropped — BatchTask promoted to molnex molix.batch.task in phase 02 |
| src/molix/data/tasks/ (AtomicDress, UnitConvert, ConstantLabel) | re-expressed in molix-data-dissolution-05 (src/molhub/dataset/transforms.py) |
| src/molix/data/tasks/neighbor.py (NeighborList) | stayed molnex: molix.batch.neighbor (phase 03); molhub wraps via SampleTask-shaped delegate (05) — wrapper is MANDATORY for pipeline cacheability, the standalone class registers as a bare callable |
| src/molix/datasets/qm9.py, revmd17.py, threebpa.py | owned by python-native-dataset-protocol-03/-04 (already in-tree: src/molhub/dataset/{qm9,revmd17,threebpa}.py) |
| src/molix/datasets/water_les.py, molrec.py | re-expressed in molix-data-dissolution-05 |
| src/molix/datasets/_extxyz.py | stayed molnex: molix.io.extxyz (phase 03) |
| src/molix/datasets/_valence_columns.py, _bond_adapter.py | stayed molnex: molix.batch (phase 03) |
| src/molix/data/{cache,dataset,collate,sampler,datamodule,group_split}.py | stayed molnex: molix.store / molix.batch (phases 01-02) |
| src/molix/data/pes_bundle.py | dropped — orphan container, zero production consumers |
| benchmarks/{train_pinet_ef_padded,train_pinet_ef_compare,bench_dataloader_datasets,bench_pinet_ef_full}.py | dropped — Pipeline+Source drivers; git history is the reference |
