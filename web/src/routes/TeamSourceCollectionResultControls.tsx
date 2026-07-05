import { type MouseEvent as ReactMouseEvent, type ReactNode } from "react";

import {
  TeamSourceFilterBar,
  TeamSourcePagination,
} from "../components/vui/product/team-management";

export type TeamSourceCollectionFilterOption<Key extends string = string> = {
  key: Key;
  label: ReactNode;
  count: ReactNode;
  selected: boolean;
};

type TeamSourceCollectionFilterBarProps<Key extends string = string> = {
  ariaLabel: string;
  options: Array<TeamSourceCollectionFilterOption<Key>>;
  onSelect: (key: Key) => void;
};

type TeamSourceCollectionPaginationProps = {
  lang: "zh" | "en";
  total: number;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  onContain?: (event: ReactMouseEvent<HTMLDivElement>) => void;
};

export function TeamSourceCollectionFilterBar<Key extends string = string>({
  ariaLabel,
  options,
  onSelect,
}: TeamSourceCollectionFilterBarProps<Key>) {
  return (
    <TeamSourceFilterBar
      ariaLabel={ariaLabel}
      options={options}
      onSelect={(key) => onSelect(key as Key)}
    />
  );
}

export function TeamSourceCollectionPagination({
  lang,
  total,
  page,
  pageSize,
  onPageChange,
  onContain,
}: TeamSourceCollectionPaginationProps) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  if (pageCount <= 1) {
    return null;
  }
  const boundedPage = Math.min(Math.max(1, page), pageCount);
  const start = (boundedPage - 1) * pageSize + 1;
  const end = Math.min(total, boundedPage * pageSize);

  return (
    <TeamSourcePagination
      ariaLabel={lang === "zh" ? "结果分页" : "Result pagination"}
      rangeLabel={lang === "zh" ? `第 ${start}-${end} 条 / 共 ${total} 条` : `${start}-${end} of ${total}`}
      page={boundedPage}
      pageCount={pageCount}
      previousLabel={lang === "zh" ? "上一页" : "Previous"}
      nextLabel={lang === "zh" ? "下一页" : "Next"}
      onPrevious={() => onPageChange(boundedPage - 1)}
      onNext={() => onPageChange(boundedPage + 1)}
      onContain={onContain}
    />
  );
}
