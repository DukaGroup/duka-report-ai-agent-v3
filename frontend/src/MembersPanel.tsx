import { Plus, Trash2 } from "lucide-react";
import type { User } from "./types";

export function MembersPanel({
  actor,
  users,
  onAdd,
  onRole,
  onRestart,
  onAccess,
  onRecover,
  onToggle,
  onRemove,
}: {
  actor: User;
  users: User[];
  onAdd: () => void;
  onRole: (user: User, role: User["role"]) => void;
  onRestart: (user: User) => void;
  onAccess: (user: User) => void;
  onRecover: (user: User) => void;
  onToggle: (user: User) => void;
  onRemove: (user: User) => void;
}) {
  const isDev = actor.role === "devs";
  return (
    <section className="panel">
      <div className="panel-heading">
        <h3>Anëtarët e hapësirës</h3>
        <button className="button primary small" onClick={onAdd}>
          <Plus size={16} /> Shto anëtar
        </button>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Anëtar</th>
              <th>Roli</th>
              <th>Gjendja</th>
              {isDev && (
                <>
                  <th>Lidhja</th>
                  <th>Databazat dhe kompanitë</th>
                </>
              )}
              <th>Veprimet</th>
            </tr>
          </thead>
          <tbody>
            {users.map((member) => (
              <tr key={member.id}>
                <td>
                  <strong>{member.name}</strong>
                  <small>{member.email}</small>
                </td>
                <td>
                  {isDev ? (
                    <select
                      aria-label={`Roli i ${member.name}`}
                      value={member.role}
                      disabled={member.id === actor.id}
                      onChange={(event) =>
                        onRole(member, event.target.value as User["role"])
                      }
                    >
                      <option value="devs">Devs</option>
                      <option value="president">President</option>
                      <option value="manager">Manager</option>
                    </select>
                  ) : member.role === "devs" ? (
                    "Devs"
                  ) : member.role === "president" ? (
                    "President"
                  ) : (
                    "Manager"
                  )}
                </td>
                <td>{member.active ? "Aktiv" : "Joaktiv"}</td>
                {isDev && (
                  <>
                    <td>
                      <button
                        className="text-button"
                        onClick={() => onRestart(member)}
                      >
                        Rinis
                      </button>
                    </td>
                    <td>
                      <button
                        className="text-button"
                        onClick={() => onAccess(member)}
                      >
                        {member.role === "manager"
                          ? "Zgjidh qasjen"
                          : "Qasje në të gjitha"}
                      </button>
                    </td>
                  </>
                )}
                <td>
                  {isDev && (
                    <>
                      <button
                        className="text-button"
                        disabled={!member.active}
                        onClick={() => onRecover(member)}
                      >
                        Rikupero llogarinë
                      </button>
                      <button
                        className="button outline small"
                        disabled={member.id === actor.id}
                        onClick={() => onToggle(member)}
                      >
                        {member.active ? "Çaktivizo" : "Aktivizo"}
                      </button>
                    </>
                  )}
                  {member.id !== actor.id &&
                    (isDev || member.role !== "devs") && (
                      <button
                        className="icon-button"
                        aria-label={`Fshi anëtarin: ${member.name}`}
                        title="Fshi anëtarin"
                        onClick={() => onRemove(member)}
                      >
                        <Trash2 size={16} />
                      </button>
                    )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
