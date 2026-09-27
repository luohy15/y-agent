import { useState } from "react";
import {
  Badge,
  Combobox,
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
 * todo 3666, Combobox in 0.3.0, freeText in 0.4.0 / todo 3695). Not mounted by any route.
 * Exists so the host Vite/Tailwind build actually resolves the package and
 * emits utilities that live only inside dist (uppercase, tracking-wide,
 * tabular-nums, the Badge tone colors, the align="center" Table cells, and
 * the Combobox popup: shadow-float, z-30, max-h-48, overflow-y-auto).
 */
const ROWS = [
  { route: "GET /api/todo", p95: 412, requests: 1804, tone: "success" as const, active: true },
  { route: "GET /api/chat/messages", p95: 266, requests: 9201, tone: "warning" as const, active: false },
];

const ENVIRONMENT_OPTIONS = [
  { value: "prod", label: "Production" },
  { value: "staging", label: "Staging" },
];

const MODEL_OPTIONS = [
  { value: "", label: "All models" },
  { value: "claude-opus", label: "claude-opus" },
  { value: "claude-sonnet", label: "claude-sonnet" },
];

export function DesignTableFixture() {
  const [environment, setEnvironment] = useState("prod");
  const [model, setModel] = useState("");
  const [query, setQuery] = useState("claude");
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
      <Combobox
        label="Model"
        value={model}
        options={MODEL_OPTIONS}
        onValueChange={setModel}
        placeholder="Search models"
      />
      <Combobox
        label="Filter models"
        freeText
        value={query}
        options={MODEL_OPTIONS}
        onValueChange={setQuery}
        placeholder="Search models"
      />
      <DateRangeInput value={range} onChange={setRange} onApply={() => {}} max="2026-09-24" />
    </div>
  );
}
