"""PDF rendering for letters, slips, receipts, transcripts and reports."""
import io
import os

from django.conf import settings
from django.contrib.staticfiles import finders
from django.http import HttpResponse
from django.template.loader import render_to_string


def _link_callback(uri, rel):
    if uri.startswith(settings.MEDIA_URL) or uri.startswith("/" + settings.MEDIA_URL):
        path = os.path.join(settings.MEDIA_ROOT, uri.split(settings.MEDIA_URL, 1)[1])
    elif uri.startswith("/" + settings.STATIC_URL) or uri.startswith(settings.STATIC_URL):
        rel_path = uri.split(settings.STATIC_URL, 1)[1]
        path = finders.find(rel_path) or os.path.join(settings.STATIC_ROOT, rel_path)
    else:
        return uri
    return path


def render_pdf(template_name, context, filename, request=None, inline=True):
    from xhtml2pdf import pisa  # imported lazily: heavy module

    html = render_to_string(template_name, context, request=request)
    buf = io.BytesIO()
    result = pisa.CreatePDF(html, dest=buf, link_callback=_link_callback, encoding="utf-8")
    if result.err:
        return HttpResponse("The document could not be generated. Please contact the administrator.", status=500)
    resp = HttpResponse(buf.getvalue(), content_type="application/pdf")
    disposition = "inline" if inline else "attachment"
    resp["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    return resp
