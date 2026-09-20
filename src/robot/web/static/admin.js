"use strict";
const provider = document.getElementById("expression.provider");
if (provider) {
  const update = () => {
    for (const name of ["local", "aws"]) {
      for (const section of document.querySelectorAll(`[data-provider="${name}"]`)) {
        section.hidden = provider.value !== name;
      }
    }
  };
  provider.addEventListener("change", update);
  // Show both provider sections after validation errors so inactive settings
  // can also be corrected without losing the selected provider.
  if (!document.querySelector(".error")) update();
}
