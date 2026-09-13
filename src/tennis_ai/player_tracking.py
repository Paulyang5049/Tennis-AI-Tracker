"""Scene-local role proposals; persistent participant identity requires review."""

from copy import deepcopy

from tennis_ai.positions import player_position


class SceneRoles:
    def __init__(self, players=2):
        self.players = players

    def update(self, players, record):
        result = deepcopy(players)
        for player in result:
            player["court_position"] = player_position(player, record)
            position = player["court_position"]["position_court_m"]
            side = "unknown"
            if position is not None:
                if position[1] > 12.485:
                    side = "near"
                elif position[1] < 11.285:
                    side = "far"
            player["side"] = side
            player["role_state"] = "candidate" if side != "unknown" else "unknown"
        capacity = self.players // 2
        for side in ("near", "far"):
            members = [p for p in result if p["side"] == side]
            if len(members) > capacity:
                for player in members:
                    player.update(side="unknown", role_state="ambiguous")
        for player in result:
            player["court_position"].update(side=player["side"], role_state=player["role_state"])
        return result
