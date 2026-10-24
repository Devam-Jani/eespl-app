// The table: a sticky header, row hover, sort by a column, filter chips ("All 4 / Late 1 / Billing
// due 2"), paging, and an empty state that says what to do next. Rows can open on click or Enter.
import type { ReactNode } from "react";
import { useMemo, useState } from "react";
import { Button, EmptyState } from "./components";

export type Column<T> = {
  key: string;
  label: string;
  render: (row: T) => ReactNode;
  /** a value to sort by; without it the column does not sort */
  sort?: (row: T) => string | number | null;
  num?: boolean;
  width?: number | string;
};

export type Filter<T> = { key: string; label: string; test: (row: T) => boolean };

type Props<T> = {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string | number;
  filters?: Filter<T>[];
  pageSize?: number;
  empty?: { title: string; hint?: ReactNode; action?: ReactNode };
  onOpen?: (row: T) => void;
  label?: string;
};

export function Table<T>({ rows, columns, rowKey, filters, pageSize = 25, empty, onOpen, label }: Props<T>) {
  const [filter, setFilter] = useState(filters?.[0]?.key ?? "");
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);
  const [page, setPage] = useState(0);
  const counts = useMemo(() => Object.fromEntries((filters ?? []).map((f) => [f.key, rows.filter(f.test).length])), [filters, rows]);
  const shown = useMemo(() => {
    const f = filters?.find((x) => x.key === filter);
    const out = f ? rows.filter(f.test) : [...rows];
    const col = sort && columns.find((c) => c.key === sort.key);
    if (col?.sort) {
      out.sort((a, b) => {
        const x = col.sort!(a);
        const y = col.sort!(b);
        if (x === y) return 0;
        if (x === null) return 1;
        if (y === null) return -1;
        return (x < y ? -1 : 1) * sort!.dir;
      });
    }
    return out;
  }, [rows, filters, filter, sort, columns]);
  const pages = Math.max(1, Math.ceil(shown.length / pageSize));
  const at = Math.min(page, pages - 1);
  const slice = shown.slice(at * pageSize, at * pageSize + pageSize);

  return (
    <div className="ui-table">
      {filters && filters.length > 0 && (
        <div className="filter-chips" role="group" aria-label="Show">
          {filters.map((f) => (
            <button
              key={f.key}
              type="button"
              className="chip"
              aria-pressed={filter === f.key}
              onClick={() => {
                setFilter(f.key);
                setPage(0);
              }}
            >
              {f.label} {counts[f.key]}
            </button>
          ))}
        </div>
      )}
      {slice.length === 0 ? (
        <EmptyState title={empty?.title ?? "Nothing here yet"} hint={empty?.hint} action={empty?.action} />
      ) : (
        <div className="table-wrap">
          <table className="table" aria-label={label}>
            <thead>
              <tr>
                {columns.map((c) => (
                  <th
                    key={c.key}
                    className={c.num ? "num" : undefined}
                    style={{ width: c.width }}
                    aria-sort={c.sort ? (sort?.key === c.key ? (sort.dir === 1 ? "ascending" : "descending") : "none") : undefined}
                    tabIndex={c.sort ? 0 : undefined}
                    onClick={c.sort ? () => setSort((s) => (s?.key === c.key ? { key: c.key, dir: s.dir === 1 ? -1 : 1 } : { key: c.key, dir: 1 })) : undefined}
                    onKeyDown={c.sort ? (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), setSort((s) => (s?.key === c.key ? { key: c.key, dir: s.dir === 1 ? -1 : 1 } : { key: c.key, dir: 1 }))) : undefined}
                  >
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {slice.map((r) => (
                <tr
                  key={rowKey(r)}
                  className={onOpen ? "clickable" : undefined}
                  tabIndex={onOpen ? 0 : undefined}
                  onClick={onOpen ? () => onOpen(r) : undefined}
                  onKeyDown={onOpen ? (e) => e.key === "Enter" && onOpen(r) : undefined}
                >
                  {columns.map((c) => (
                    <td key={c.key} className={c.num ? "num" : undefined}>
                      {c.render(r)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {pages > 1 && (
        <nav className="pager" aria-label="Pages">
          <Button size="small" disabled={at === 0} onClick={() => setPage(at - 1)}>
            Previous
          </Button>
          <span>
            Page {at + 1} of {pages} · {shown.length} rows
          </span>
          <Button size="small" disabled={at >= pages - 1} onClick={() => setPage(at + 1)}>
            Next
          </Button>
        </nav>
      )}
    </div>
  );
}
