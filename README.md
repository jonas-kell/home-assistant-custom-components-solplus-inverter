# HomeAssistant Custom Components SOLPLUS Inverter


Readout the information from SOLPLUS Inverters (SOLPLUS- 25,50,55) (Manufactured by Solutronic AG). Install it via HACS.

## Hacs Integration

Example `configuration.yaml` entry

```
sensor:
    - platform: solplus_sensor
      devices:
          my_inverter:
              name: My Inverter
              ip_address: 192.168.2.XXX
```

-   `name`: Name duh
-   `ip`: The IP-Address that is used to talk to the inverter (Needs to be set in the inverter menu, see provided-explanation-pdf)
