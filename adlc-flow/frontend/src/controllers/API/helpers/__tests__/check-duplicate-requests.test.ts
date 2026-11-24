import { checkDuplicateRequestAndStoreRequest } from "../check-duplicate-requests";

beforeEach(() => {
  localStorage.clear();
  jest.spyOn(Date, "now").mockReturnValue(1000);
});

afterEach(() => jest.restoreAllMocks());

test("independent project pickers may refresh the project list together", () => {
  const request = { method: "get", url: "/api/v1/projects/" };
  checkDuplicateRequestAndStoreRequest(request);
  expect(() => checkDuplicateRequestAndStoreRequest(request)).not.toThrow();
});

test("other repeated GETs retain the duplicate request guard", () => {
  const request = { method: "get", url: "/api/v1/adlc/local-projects/" };
  checkDuplicateRequestAndStoreRequest(request);
  expect(() => checkDuplicateRequestAndStoreRequest(request)).toThrow(
    "Duplicate request:",
  );
});

test.each(["/api/v1/adlc/live/intake", "/api/v1/adlc/live/runs/run-a", "/api/v1/adlc/live/attention"])(
  "independent live observers may read %s together without a false cancellation", (url) => {
    const request = { method: "get", url };
    checkDuplicateRequestAndStoreRequest(request);
    expect(() => checkDuplicateRequestAndStoreRequest(request)).not.toThrow();
  },
);

test("POST requests retain the existing duplicate-guard behavior", () => {
  const request = { method: "post", url: "/api/v1/projects/" };
  checkDuplicateRequestAndStoreRequest(request);
  expect(() => checkDuplicateRequestAndStoreRequest(request)).not.toThrow();
  expect(localStorage.getItem("lastMethodCalled")).toBe("post");
});
