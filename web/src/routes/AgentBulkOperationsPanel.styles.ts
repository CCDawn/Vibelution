import { vuiFormLabelClass } from "../components/vui/forms/formClasses";

const styles = {
  bulkPromptPicker: "min-w-0 max-w-full flex-wrap [&_select]:min-w-0 [&_select]:max-w-full",
  bulkPromptLabel: `${vuiFormLabelClass} min-w-0 max-w-full break-words`,
} as const;

export default styles;
