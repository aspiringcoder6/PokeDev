import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import HarnessRouteRedirect from "./harness-route-redirect";

jest.mock("@/customization/components/custom-navigate", () => {
  const { Navigate } = jest.requireActual("react-router-dom");
  return { CustomNavigate: Navigate };
});

function Target() {
  const location = useLocation();
  return <p>{location.pathname + location.search + location.hash}</p>;
}

test("legacy saved links retain their session and fragment on the product route", async () => {
  render(
    <MemoryRouter initialEntries={["/harness-demo/?run=retained#result"]}>
      <Routes>
        <Route path="/harness-demo/" element={<HarnessRouteRedirect />} />
        <Route path="/runtime-sessions/" element={<Target />} />
      </Routes>
    </MemoryRouter>,
  );
  expect(
    await screen.findByText("/runtime-sessions/?run=retained#result"),
  ).toBeInTheDocument();
});
