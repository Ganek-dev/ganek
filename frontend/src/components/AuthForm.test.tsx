import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AuthForm } from "./AuthForm";

describe("AuthForm", () => {
  it("renders title, fields and submit button", () => {
    render(
      <AuthForm
        title="Sign in to Vetd"
        submitLabel="Sign in"
        fields={[
          { name: "email", label: "Email", type: "email" },
          { name: "password", label: "Password", type: "password" },
        ]}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByRole("heading", { name: "Sign in to Vetd" })).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeRequired();
    expect(screen.getByLabelText("Password")).toBeRequired();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });
});
