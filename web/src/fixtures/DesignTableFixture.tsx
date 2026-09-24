import { useState } from "react";
import {
  Badge,
  DateRangeInput,
  Select,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeaderCell,
  TableRow,
  TableSortHeader,
  type DateRange,
} from "@y/design";

/**
 * Host consumption fixture for @y/design (todo 3657, extended 0.2.0 in
 * todo 3666). Not mounted by any route. Exists so the host Vite/Tailwind
 * build actually resolves the package and emits utilities that live only
 * inside dist/index.js (uppercase, tracking-wide, tabular-nums, the
 * Badge tone colors, and the align="center" Table cells).
 */
const ROWS = [
  { route: "GET /api/todo", p95: 412, requests: 1804, tone: "success" as const, active: true },
  { route: "GET /api/chat/messages", p95: 266, requests: 9201, tone: "warning" as const, active: false },
];

const ENVIRONMENT_OPTIONS = [
  { value: "prod", label: "Production" },
  { value: "staging", label: "Staging" },
];

export function DesignTableFixture() {
  const [environment, setEnvironment] = useState("prod");
  const [range, setRange] = useState<DateRange>({ from: "", to: "2026-09-24" });

  return (
    <div className="grid gap-3">
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
              <TableHeaderCell align="center">Active</TableHeaderCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {ROWS.map((row) => (
              <TableRow key={row.route}>
                <TableCell>
                  {row.route} <Badge tone={row.tone}>{row.tone}</Badge>
                </TableCell>
                <TableCell align="right">{row.p95}</TableCell>
                <TableCell align="right">{row.requests}</TableCell>
                <TableCell align="center">{row.active ? "yes" : "no"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
      <Select
        label="Environment"
        value={environment}
        options={ENVIRONMENT_OPTIONS}
        onValueChange={setEnvironment}
        error="Unreachable"
        className="aria-invalid:border-sol-red"
      />
      <DateRangeInput value={range} onChange={setRange} onApply={() => {}} max="2026-09-24" />
    </div>
  );
}
