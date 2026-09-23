import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeaderCell,
  TableRow,
  TableSortHeader,
} from "@y/design";

/**
 * Host consumption fixture for @y/design Table (todo 3657).
 * Not mounted by any route. Exists so the host Vite/Tailwind build
 * actually resolves the package and emits utilities that live only
 * inside dist/index.js (uppercase, tracking-wide, tabular-nums).
 */
const ROWS = [
  { route: "GET /api/todo", p95: 412, requests: 1804 },
  { route: "GET /api/chat/messages", p95: 266, requests: 9201 },
];

export function DesignTableFixture() {
  return (
    <TableContainer>
      <Table>
        <caption className="sr-only">Design table fixture</caption>
        <TableHead>
          <TableRow>
            <TableSortHeader direction="desc" onSort={() => {}}>
              Route
            </TableSortHeader>
            <TableHeaderCell align="right">p95</TableHeaderCell>
            <TableHeaderCell align="right">Requests</TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {ROWS.map((row) => (
            <TableRow key={row.route}>
              <TableCell>{row.route}</TableCell>
              <TableCell align="right">{row.p95}</TableCell>
              <TableCell align="right">{row.requests}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
