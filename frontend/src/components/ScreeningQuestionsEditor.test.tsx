import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ScreeningQuestion } from "@/lib/api";

import { ACK_HELP, ScreeningQuestionsEditor, newLocalQuestion } from "./ScreeningQuestionsEditor";

const PERMIT: ScreeningQuestion = {
  id: "sq_0000aa01",
  type: "yes_no",
  prompt: "Can you work in Germany?",
  options: null,
  preferred: "yes",
  required: true,
};
const DAYS: ScreeningQuestion = {
  id: "sq_0000aa02",
  type: "single_choice",
  prompt: "Days on site?",
  options: ["0", "1-2"],
  preferred: null,
  required: false,
};
const ACK: ScreeningQuestion = {
  id: "sq_0000aa04",
  type: "acknowledgment",
  prompt: "I confirm the information is accurate",
  options: null,
  preferred: null,
  required: true,
};

function last(onChange: ReturnType<typeof vi.fn>): ScreeningQuestion[] {
  return onChange.mock.calls.at(-1)![0] as ScreeningQuestion[];
}

describe("ScreeningQuestionsEditor", () => {
  afterEach(() => vi.restoreAllMocks());

  it("adds a yes/no question with a fresh id, optional, no preferred answer", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<ScreeningQuestionsEditor value={[]} onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: "Add question" }));
    const next = last(onChange);
    expect(next).toHaveLength(1);
    expect(next[0].type).toBe("yes_no");
    expect(next[0].id).toMatch(/^sq_[0-9a-f]{8}$/);
    expect(next[0].required).toBe(false);
    expect(next[0].preferred).toBeNull();
  });

  it("newLocalQuestion makes an acknowledgment required with no options or preferred", () => {
    const q = newLocalQuestion("acknowledgment");
    expect(q.required).toBe(true);
    expect(q.options).toBeNull();
    expect(q.preferred).toBeNull();
    expect(newLocalQuestion("single_choice").options).toEqual(["", ""]);
  });

  it("renders a row per question with prompt, type, preferred and required controls", () => {
    render(<ScreeningQuestionsEditor value={[PERMIT, DAYS]} onChange={vi.fn()} />);
    const first = screen.getByRole("group", { name: "Question 1" });
    expect(within(first).getByLabelText("Prompt")).toHaveValue("Can you work in Germany?");
    expect(within(first).getByLabelText("Type")).toHaveValue("yes_no");
    expect(within(first).getByLabelText("Preferred answer")).toHaveValue("yes");
    expect(within(first).getByLabelText("Required")).toBeChecked();
    const second = screen.getByRole("group", { name: "Question 2" });
    expect(within(second).getByLabelText("Option 1")).toHaveValue("0");
    expect(within(second).getByLabelText("Option 2")).toHaveValue("1-2");
    expect(within(second).getByLabelText("Preferred answer")).toHaveValue("");
  });

  it("switching to single choice opens two empty options and clears the preferred answer", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<ScreeningQuestionsEditor value={[PERMIT]} onChange={onChange} />);
    await user.selectOptions(screen.getByLabelText("Type"), "single_choice");
    const [q] = last(onChange);
    expect(q.type).toBe("single_choice");
    expect(q.options).toEqual(["", ""]);
    expect(q.preferred).toBeNull();
  });

  it("acknowledgment rows show Always required and the help copy, no preferred picker", () => {
    render(<ScreeningQuestionsEditor value={[ACK]} onChange={vi.fn()} />);
    const row = screen.getByRole("group", { name: "Question 1" });
    expect(within(row).getByText("Always required")).toBeInTheDocument();
    expect(within(row).getByText(ACK_HELP)).toBeInTheDocument();
    expect(within(row).queryByLabelText("Preferred answer")).toBeNull();
    expect(within(row).queryByLabelText("Required")).toBeNull();
  });

  it("edits the prompt, adds and removes options, toggles required", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<ScreeningQuestionsEditor value={[DAYS]} onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: "Add option" }));
    expect(last(onChange)[0].options).toEqual(["0", "1-2", ""]);
    await user.click(screen.getByRole("button", { name: "Remove option 1" }));
    expect(last(onChange)[0].options).toEqual(["1-2"]);
    await user.click(screen.getByLabelText("Required"));
    expect(last(onChange)[0].required).toBe(true);
    await user.type(screen.getByLabelText("Prompt"), "!");
    expect(last(onChange)[0].prompt).toBe("Days on site?!");
  });

  it("moves rows up and down and deletes them", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<ScreeningQuestionsEditor value={[PERMIT, DAYS]} onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: "Move question 2 up" }));
    expect(last(onChange).map((q) => q.id)).toEqual([DAYS.id, PERMIT.id]);
    await user.click(screen.getByRole("button", { name: "Move question 1 down" }));
    expect(last(onChange).map((q) => q.id)).toEqual([DAYS.id, PERMIT.id]);
    await user.click(screen.getByRole("button", { name: "Remove question 1" }));
    expect(last(onChange).map((q) => q.id)).toEqual([DAYS.id]);
  });

  it("Reset to company defaults asks to confirm only when the list is not empty", async () => {
    const user = userEvent.setup();
    const onReset = vi.fn();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const { rerender } = render(
      <ScreeningQuestionsEditor value={[PERMIT]} onChange={vi.fn()} onReset={onReset} />,
    );
    await user.click(screen.getByRole("button", { name: "Reset to company defaults" }));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(onReset).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    await user.click(screen.getByRole("button", { name: "Reset to company defaults" }));
    expect(onReset).toHaveBeenCalledTimes(1);
    rerender(<ScreeningQuestionsEditor value={[]} onChange={vi.fn()} onReset={onReset} />);
    await user.click(screen.getByRole("button", { name: "Reset to company defaults" }));
    expect(confirm).toHaveBeenCalledTimes(2); // no dialog for an empty list
    expect(onReset).toHaveBeenCalledTimes(2);
  });

  it("has no reset button without onReset and caps the list at twenty", () => {
    const twenty = Array.from({ length: 20 }, (_, i) => ({ ...PERMIT, id: `sq_000000${String(i).padStart(2, "0")}` }));
    render(<ScreeningQuestionsEditor value={twenty} onChange={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Reset to company defaults" })).toBeNull();
    expect(screen.getByRole("button", { name: "Add question" })).toBeDisabled();
  });
});
