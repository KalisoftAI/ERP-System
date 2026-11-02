export default function Table({
  columns,
  data,
  keyField = 'id',
  onRowClick,
  stickyColumns = [],
  rightSticky = false,
  dense = false,
  empty,
}) {
  if (!data || data.length === 0) {
    return empty || <div className="text-center py-12 text-sm text-slate-400">No data found</div>
  }
  return (
    <div className="table-wrap">
      <table className={`data-table ${dense ? 'table-dense' : ''}`}>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={stickyColumns.includes(c.key) ? 'col-sticky' : ''}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {data.map((row, ri) => (
            <tr
              key={row[keyField] ?? ri}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              onKeyDown={onRowClick ? (e) => {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onRowClick(row) }
              } : undefined}
              tabIndex={onRowClick ? 0 : undefined}
              role={onRowClick ? 'button' : undefined}
              className={onRowClick ? 'cursor-pointer hover:bg-slate-50 transition-colors focus:outline-none focus:bg-slate-50' : ''}
            >
              {columns.map((c) => {
                const sticky = stickyColumns.includes(c.key)
                return (
                  <td key={c.key} className={sticky ? 'col-sticky' : ''}>
                    {c.render ? c.render(row) : row[c.key]}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}