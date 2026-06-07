// Runs after the test framework is initialised (setupFilesAfterEnv).
// Restores the safe fetch default after every test so that background
// setInterval polling (refreshChannels, refreshPresence, etc.) never receives
// a response without .json(), which would crash the process before Jest can
// print the coverage report.
afterEach(() => {
  global.fetch.mockImplementation(() =>
    Promise.resolve({
      ok: true,
      json: () => Promise.resolve({}),
      text: () => Promise.resolve(""),
    }),
  );
});
