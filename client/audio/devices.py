"""Persist device identities; PortAudio indices may change between launches."""


def list_devices(backend):
    hosts = backend.query_hostapis()
    return [
        dict(
            index=index,
            name=device["name"],
            host=hosts[device["hostapi"]]["name"],
            input=bool(device["max_input_channels"]),
            output=bool(device["max_output_channels"]),
        )
        for index, device in enumerate(backend.query_devices())
    ]


def resolve_device(backend, selection, direction):
    if not selection:
        return None
    if not isinstance(selection, dict) or direction not in ("input", "output"):
        raise ValueError("Некорректное выбранное аудиоустройство")
    matches = [
        device
        for device in list_devices(backend)
        if device[direction]
        and device["name"] == selection.get("name")
        and device["host"] == selection.get("host")
    ]
    if len(matches) != 1:
        raise ValueError(
            "Выбранное аудиоустройство недоступно. Выберите устройство в настройках."
        )
    return matches[0]["index"]
