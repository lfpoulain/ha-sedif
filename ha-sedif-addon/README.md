# SEDIF - Relevé de consommation d'eau (Home Assistant Add-on)

Addon Home Assistant qui se connecte au portail SEDIF, récupère les 40 derniers jours de relevés,
et publie les métriques essentielles (dernier relevé, semaine/mois en cours, surconsommation).

## Installation rapide

1. Copier ce dossier dans `/addons/local/ha-sedif-addon`.
2. Redémarrer Home Assistant ou recharger le store d'addons.
3. Installer l'addon **SEDIF Water Consumption** et configurer les options.

## Configuration

- `sedif_username`: Email ou identifiant SEDIF.
- `sedif_password`: Mot de passe SEDIF.
- `debug`: Active les logs debug (défaut: false).
- `sensor_prefix`: Préfixe des entités (défaut: sedif).
- `refresh_interval_minutes`: Fréquence d'exécution en minutes (défaut: 360).

## Fonctionnement

- SEDIF ne fournit pas la consommation du jour en cours : l'addon prend la dernière date disponible.
- La collecte est **fixée à 40 jours** (base des moyennes et de la surconsommation).
- La semaine/mois en cours sont calculés à partir des relevés journaliers.
- Si l'API ne renvoie pas les euros, l'addon calcule le coût avec `prixMoyenEau` (€/m³).
- Tous les montants en euros sont arrondis au centime.

## Capteurs créés

- `sensor.<prefix>_daily`: consommation du dernier relevé (L) + détails m³/EUR.
- `sensor.<prefix>_daily_euros`: coût du dernier relevé (EUR).
- `sensor.<prefix>_max_m3`: consommation maximale (m³) + date.
- `sensor.<prefix>_avg_m3`: consommation moyenne (m³).
- `sensor.<prefix>_meter_index`: dernier index compteur (m³) + date.
- `sensor.<prefix>_info`: informations compteur (PDS, compteur, période API).
- `sensor.<prefix>_week_to_date_m3`: consommation semaine en cours (m³/L/EUR).
- `sensor.<prefix>_month_to_date_m3`: consommation mois en cours (m³/L/EUR).
- `sensor.<prefix>_monthly_estimate_euros`: estimation facture mensuelle (EUR).
- `sensor.<prefix>_last_reading_date`: date du dernier relevé.
- `sensor.<prefix>_overconsumption`: niveau de surconsommation (référence 40 jours).
