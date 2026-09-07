-- Registry foreign keys introduced by the domain-independent retrieval schema.
-- Keep both indexes: the composite FK is ordered by document_type first, so it
-- cannot also serve source_kind-only lookups.
create index if not exists documents_source_kind_registry_idx
  on legal.documents (source_kind);

create index if not exists documents_document_type_source_kind_idx
  on legal.documents (document_type, source_kind);

create index if not exists legal_units_unit_type_registry_idx
  on legal.legal_units (unit_type);
