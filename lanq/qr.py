import qrcode
from qrcode.image.svg import SvgPathImage


def qr_svg(data: str) -> str:
    code = qrcode.QRCode(border=4, box_size=8)
    code.add_data(data)
    code.make(fit=True)
    image = code.make_image(image_factory=SvgPathImage)
    svg = image.to_string().decode("utf-8")
    root_close = svg.index(">", svg.index("<svg"))
    background = '<rect width="100%" height="100%" fill="white"/>'
    return svg[: root_close + 1] + background + svg[root_close + 1 :]
