import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, type UserOut } from "@/lib/api";
import { LocaleProvider } from "@/lib/i18n/locale";

import { SignInMethodsCard } from "./SignInMethodsCard";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: { ...original.api, unlinkSignInMethod: vi.fn() },
  };
});

const mockedApi = vi.mocked(api);

function user(over: Partial<UserOut> = {}): UserOut {
  return {
    id: "u1",
    company_id: "c1",
    email: "a@acme.dev",
    role: "admin",
    has_password: true,
    google_linked: false,
    sso_linked: false,
    ...over,
  };
}

describe("SignInMethodsCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders nothing when no provider is on and nothing is linked", () => {
    const { container } = render(
      <SignInMethodsCard user={user()} google={false} onUserChange={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("lists the instance's providers with their link state", () => {
    render(
      <SignInMethodsCard
        user={user({ google_linked: true })}
        google
        oidcName="Acme SSO"
        onUserChange={vi.fn()}
      />,
    );
    expect(screen.getByText("Google")).toBeInTheDocument();
    expect(screen.getByText("Linked")).toBeInTheDocument();
    expect(screen.getByText("Acme SSO")).toBeInTheDocument();
    expect(screen.getByText(/Not linked · sign in with Acme SSO once/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unlink Google" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Unlink Acme SSO" })).toBeNull();
  });

  it("still shows a linked identity after its provider was turned off", () => {
    render(
      <SignInMethodsCard user={user({ sso_linked: true })} google={false} onUserChange={vi.fn()} />,
    );
    expect(screen.getByText("Single sign-on")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unlink Single sign-on" })).toBeEnabled();
    expect(screen.queryByText("Google")).toBeNull();
  });

  it("unlinks after the confirm and hands the updated user back", async () => {
    const updated = user({ sso_linked: false });
    mockedApi.unlinkSignInMethod.mockResolvedValue(updated);
    const onUserChange = vi.fn();
    render(
      <SignInMethodsCard
        user={user({ sso_linked: true })}
        google={false}
        oidcName="Keycloak"
        onUserChange={onUserChange}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Unlink Keycloak" }));
    expect(screen.getByText(/Unlink Keycloak\? You can no longer sign in with it/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Unlink Keycloak" }));
    await waitFor(() => expect(mockedApi.unlinkSignInMethod).toHaveBeenCalledWith("sso"));
    expect(onUserChange).toHaveBeenCalledWith(updated);
  });

  it("cancel closes the confirm without calling the API", async () => {
    render(
      <SignInMethodsCard user={user({ google_linked: true })} google onUserChange={vi.fn()} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Unlink Google" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByText(/You can no longer sign in with it/)).toBeNull();
    expect(mockedApi.unlinkSignInMethod).not.toHaveBeenCalled();
  });

  it("disables unlinking the only way in for a passwordless account", () => {
    render(
      <SignInMethodsCard
        user={user({ has_password: false, google_linked: true })}
        google
        oidcName="Acme SSO"
        onUserChange={vi.fn()}
      />,
    );
    expect(screen.getByText("Linked · your only way to sign in")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unlink Google" })).toBeDisabled();
  });

  it("lets a passwordless account with two identities drop one", () => {
    render(
      <SignInMethodsCard
        user={user({ has_password: false, google_linked: true, sso_linked: true })}
        google
        oidcName="Acme SSO"
        onUserChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "Unlink Google" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Unlink Acme SSO" })).toBeEnabled();
  });

  it("is read-only when locked", () => {
    render(
      <SignInMethodsCard
        user={user({ google_linked: true })}
        google
        locked
        onUserChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "Unlink Google" })).toBeDisabled();
  });

  it("shows the server's refusal inside the confirm", async () => {
    mockedApi.unlinkSignInMethod.mockRejectedValue(
      new ApiError(409, "This is your only way to sign in."),
    );
    render(
      <SignInMethodsCard user={user({ google_linked: true })} google onUserChange={vi.fn()} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Unlink Google" }));
    await userEvent.click(screen.getByRole("button", { name: "Unlink Google" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This is your only way to sign in.");
  });
});

describe("SignInMethodsCard in German", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.setItem("ganek.admin.locale", "de");
  });
  afterEach(() => window.localStorage.clear());

  it("renders the methods, the confirm and the fallback error in German", async () => {
    mockedApi.unlinkSignInMethod.mockRejectedValue(new ApiError(500, "boom"));
    render(
      <LocaleProvider>
        <SignInMethodsCard
          user={user({ google_linked: true })}
          google
          oidcName=""
          onUserChange={vi.fn()}
        />
      </LocaleProvider>,
    );
    expect(screen.getByText("Anmeldemethoden")).toBeInTheDocument();
    expect(screen.getByText("Verknüpft")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Google trennen" }));
    expect(screen.getByText(/^Google trennen\?/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Abbrechen" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Google trennen" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Google konnte nicht getrennt werden. Bitte erneut versuchen.",
    );
  });

  it("names unlinked SSO and the only way in in German", () => {
    render(
      <LocaleProvider>
        <SignInMethodsCard
          user={user({ has_password: false, google_linked: true })}
          google
          oidcName=""
          onUserChange={vi.fn()}
        />
      </LocaleProvider>,
    );
    expect(screen.getByText("Verknüpft · Ihre einzige Anmeldemöglichkeit")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Google trennen" })).toHaveAttribute(
      "title",
      expect.stringContaining("Legen Sie zuerst ein Passwort fest"),
    );
  });

  it("falls back to the German single sign-on label", () => {
    render(
      <LocaleProvider>
        <SignInMethodsCard
          user={user({ sso_linked: true })}
          google={false}
          onUserChange={vi.fn()}
        />
      </LocaleProvider>,
    );
    expect(screen.getByRole("button", { name: "Single Sign-on trennen" })).toBeInTheDocument();
  });
});
