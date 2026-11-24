import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { ProtectedRoute } from "./index";

jest.mock("@/controllers/API/queries/auth", () => ({
  useRefreshAccessToken: () => ({ mutate: jest.fn() }),
}));
jest.mock("@/stores/authStore", () => ({
  __esModule: true,
  default: (select: (state: unknown) => unknown) =>
    select({ isAuthenticated: false, autoLogin: false }),
}));
jest.mock("@/customization/components/custom-navigate", () => ({
  CustomNavigate: ({ to }: { to: string }) => (
    <output data-testid="destination">{to}</output>
  ),
}));

it("preserves project, issue and fragment through login without splitting query parameters", () => {
  const destination =
    "/work?project=project-a&view=issues&issue=proposal-a#answers";
  window.history.replaceState({}, "", destination);
  render(
    <ProtectedRoute>
      <div>Protected</div>
    </ProtectedRoute>,
  );
  const url = new URL(
    screen.getByTestId("destination").textContent!,
    "http://localhost",
  );
  expect(url.pathname).toBe("/login");
  expect(url.searchParams.get("redirect")).toBe(destination);
  expect([...url.searchParams.keys()]).toEqual(["redirect"]);
});

it("keeps the ordinary home login destination", () => {
  window.history.replaceState({}, "", "/flows");
  render(
    <ProtectedRoute>
      <div>Protected</div>
    </ProtectedRoute>,
  );
  expect(screen.getByTestId("destination")).toHaveTextContent("/login");
  expect(screen.getByTestId("destination").textContent).toBe("/login");
});
