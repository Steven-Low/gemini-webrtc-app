// Session.js (top-level in-memory singleton)
let callerId = Math.floor(100000 + Math.random() * 900000).toString();

export const getCallerId = () => callerId;

export const regenerateCallerId = () => {
  callerId = Math.floor(100000 + Math.random() * 900000).toString();
};
