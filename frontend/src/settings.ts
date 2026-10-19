export type SettingsTab =
  | "appearance"
  | "account"
  | "models"
  | "sources"
  | "members"
  | "overview"
  | "traffic"
  | "activity";

export function settingsSections(
  role: string,
): { id: SettingsTab; label: string; group: string }[] {
  const sections: { id: SettingsTab; label: string; group: string }[] = [
    { id: "appearance", label: "Pamja", group: "Preferencat" },
  ];
  if (role === "devs")
    sections.push(
      { id: "account", label: "Llogaria", group: "Preferencat" },
      { id: "models", label: "Modeli", group: "Hapësira" },
      { id: "sources", label: "Burimet e të dhënave", group: "Hapësira" },
    );
  if (role === "devs" || role === "president")
    sections.push({
      id: "members",
      label: "Anëtarët dhe qasja",
      group: "Hapësira",
    });
  if (role === "devs")
    sections.push(
      { id: "overview", label: "Përmbledhje", group: "Administrimi" },
      { id: "traffic", label: "Trafiku", group: "Administrimi" },
      {
        id: "activity",
        label: "Regjistri i aktivitetit",
        group: "Administrimi",
      },
    );
  return sections;
}
