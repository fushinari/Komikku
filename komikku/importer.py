import json
import os
from urllib.parse import urlsplit

from gi.repository import GLib

from komikku.models import Manga
from komikku.servers import get_servers_list


def import_from_file(window, file_path):
    """ Import mangas from a Tachiyomi backup file """
    # Commented out servers are servers present in my Tachiyomi backup but not found in Komikku.
    # More importantly, I'm not sure these server codes are the same for everyone. I really really doubt that.
    komikku_servers = {
        # '4637971935551651734': 'Guya',
        '5509224355268673176': 'kireicake:jaiminisbox',
        # '1210319763629695403': 'LH',
        '9': 'mangasee',
        # '3606721916149050760': 'MangaSushi',
        '1998944621602463790': 'mangaplus',
        # '1290583086539489022': 'NinjaScans',
        '2522335540328470744': 'webtoon',
        '9064882169246918586': 'jaiminisbox',
        '4055499394183150749': 'leviatanscans:genkan',
        '2499283573021220255': 'mangadex',
        '1538249443376436084': 'xkcd',
        '2050732366638281655': 'zeroscans:genkan',
    }

    def add_manga(manga_data, server):
        """ Add a manga to the library using skeleton data """
        manga = Manga.new(manga_data, server)
        if manga:
            print(f"Added {manga_data['name']} successfully... Maybe.")
            GLib.idle_add(complete, manga)
            return manga
        print(f"Seems like \"{manga_data['name']}\" is already in the library.")
        return None

    def complete(manga):
        window.library.on_manga_added(manga)
        return False

    def get_server(server_id):
        """ Get server instance with server name """
        servers_list = get_servers_list()
        for item in servers_list:
            if item['id'] == server_id:
                return getattr(item['module'], item['class_name'])()
        return None

    if os.path.exists(file_path):
        with open(file_path, 'r') as backup:
            backup_json = json.load(backup)

    for i in range(0, len(backup_json['mangas'])):
        server_code = str(backup_json['mangas'][i]['manga'][2])
        server_id = komikku_servers.get(server_code, None)
        if server_id:
            # Unlike Komikku, Tachiyomi doesn't use a 'slug', it simply stores the top-level URL for the manga.
            tachi_slug = backup_json['mangas'][i]['manga'][0]
            if server_id == 'webtoon':
                # In Webtoon's case, the slug is irrelevant but still stored. Instead, the URL is more relevant.
                # Tachiyomi and Komikku are similar only in this case from my backup. Maybe I just don't use many servers?
                url = tachi_slug
                slug = urlsplit(tachi_slug).query.split('=')[-1]
            elif server_id == 'xkcd':
                # xkcd has no slug or url in Komikku unlike in Tachiyomi. The server module handles everything.
                url = None
                slug = None
            else:
                # This basic way of getting the slug is applicable to most servers and most servers don't use a URL.
                url = None
                slug = tachi_slug.strip('/').split('/')[-1]

            # Only skeleton data needs to be constructed with very basic info. Komikku handles metadata updation on library update.
            manga_data = dict(
                name=backup_json['mangas'][i]['manga'][1],
                url=url,
                slug=slug,
                server_id=server_id,
                cover=None,
                chapters=[],
            )

            add_manga(manga_data, get_server(server_id))
