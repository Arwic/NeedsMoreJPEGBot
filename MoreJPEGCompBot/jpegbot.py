"""
This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

Author: Reddit: /u/Arwic
		GitHub: https://github.com/Arwic
"""

import traceback
import praw
import time
import sqlite3
import threading
import os
import pyimgur
import optparse
from PIL import Image
from oauth import reddit_app_ua, reddit_app_id, reddit_app_secret, reddit_app_uri, reddit_app_refresh
from oauth import imgur_app_id, imgur_app_secret

subreddits = 'Arwic'  # this can be a multireddit, i.e. sub1+sub2+sub3
white_listed_authors = []
black_listed_authors = []
triggers = [
    'needs more jpeg compression',
    'needs more jpg compression',
    'nice jpeg',
    'nice jpg',
    'needs more jpeg',
    'needs more jpg']
max_pull = 100
pull_period = 30
compression_quality = 5
direct_imgur_link = 'http://i.imgur.com/'
indirect_imgur_link = 'http://imgur.com/'
imgur_url = 'imgur.com'
db_file = 'jpegbot.db'
temp_dir = 'temp'
reply_template = \
'''
[Here you go](%s)

---

^This ^message ^was ^created ^by ^a ^bot [^[Contact ^author]](http://np.reddit.com/message/compose/?to=Arwic&amp;subject=MoreJPEGCompBot)[^[Source ^code]](https://github.com/Arwic/RedditBots)
'''
debug_truncation_len = 20
reddit = None
imgur = None
sql = None
cur = None


def auth_reddit():
    print('Attempting to authenticate with reddit...')
    global reddit
    reddit = praw.Reddit(reddit_app_ua)
    reddit.set_oauth_app_info(reddit_app_id, reddit_app_secret, reddit_app_uri)
    reddit.refresh_access_information(reddit_app_refresh)
    print('Success')


def auth_imgur():
    print('Attempting to authenticate with imgur...')
    global imgur
    imgur = pyimgur.Imgur(imgur_app_id, imgur_app_secret)
    print('Success!')


def auth_db():
    print('Attempting to connect to database...')
    global sql, cur
    sql = sqlite3.connect(db_file)
    cur = sql.cursor()
    cur.execute('CREATE TABLE IF NOT EXISTS processed(ID TEXT)')
    sql.commit()
    print('Success!')
    return sql, cur


def has_replied(sql, cur, cid):
    cur.execute('SELECT * FROM processed WHERE ID=?', [cid])
    if cur.fetchone():
        return True
    cur.execute('INSERT INTO processed VALUES(?)', [cid])
    sql.commit()
    return False


def imgur_url_to_id(url):
    if direct_imgur_link in url:
        return url[19:-4]
    elif indirect_imgur_link in url:
        return url[17:]
    else:
        print('Imgur to ID: Bad URL: %s' % url)
        return None


def download_image(imgur_id):
    print('Downloading image', imgur_id)
    global imgur
    image_handle = imgur.get_image(imgur_id)
    path = image_handle.download(path=temp_dir, overwrite=True)
    print('Success!', path)
    return path


def upload_image(path):
    print('Uploading image', path)
    global imgur
    uploaded_image = imgur.upload_image(path, title="NEEDS MORE JPEG COMPRESSION")
    print('Success!', uploaded_image.link)
    return uploaded_image


def compress_image(img_path):
    print('Compressing image', img_path)
    compressed_path = os.path.splitext(img_path)[0] + '_c.jpg'
    if os.path.isfile(compressed_path):
        os.remove(compressed_path)
    image = Image.open(img_path)
    image.save(compressed_path, 'JPEG', quality=compression_quality)
    print('Success!', compressed_path)
    return compressed_path


def reply(submission, comment):
    print('Reply: Replying to comment id="%s" author="%s", body="%s"' % (comment.id, comment.author,
                                                                         comment.body[:debug_truncation_len]))
    while True:
        imgur_id = imgur_url_to_id(submission.url)
        if imgur_id is None:
            break
        image_path = download_image(imgur_id)
        compressed_image_path = compress_image(image_path)
        uploaded_image = upload_image(compressed_image_path)
        try:
            comment.reply(reply_template % uploaded_image.link)
            print('Reply: Reply was submitted successfully')
            break
        except praw.errors.RateLimitExceeded as error:
            print('Rate limit exceeded! Sleeping for', error.sleep_time, 'seconds')
            time.sleep(error.sleep_time)


def scan():
    print('Scanning subreddits: %s', subreddits)
    sr = reddit.get_subreddit(subreddits)
    submissions = sr.get_new(limit=max_pull)
    for submission in submissions:
        print('Parsing submission id="%s" name="%s" author="%s"' % (submission.id, submission.name, submission.author))
        # check if it is an imgur submission
        if imgur_url not in submission.url:
            print('Submission not supported', submission.url)
            continue
        for comment in submission.comments:
            # check if the author still exists
            try:
                c_author = comment.author.name.lower()
                print('Scan: Parsing comment id="%s" author="%s", body="%s"' %
                      (comment.id, comment.author, comment.body[:debug_truncation_len]))
            except AttributeError:
                print('Scan: Comment id="%s" has been deleted or removed, ignoring it' % comment.id)
                continue

            # check if we have already replied to this comment
            if has_replied(sql, cur, comment.id):
                print('Scan: Comment id="%s" has already been parsed, ignoring it' % comment.id)
                continue

            # check if the comment author is white listed
            if white_listed_authors != []:
                white_listed = False
                for author in white_listed_authors:
                    if author.lower() == c_author:
                        white_listed = True
                        break
                if not white_listed:
                    print('Scan: author="%s" is not white listed, ignoring comment' % c_author)
                    continue
            # check if the comment author is black listed
            if black_listed_authors != []:
                black_listed = False
                for author in black_listed_authors:
                    if author.lower() == c_author.lower():
                        black_listed = True
                        break
                if black_listed:
                    print('Scan: author="%s" is black listed, ignoring comment' % c_author)
                    continue
            c_body = comment.body.lower()
            if any(trigger in c_body.lower() for trigger in triggers):
                reply(submission, comment)


def prepare_env():
    if not os.path.isdir(temp_dir):
        os.mkdir(temp_dir)


def main():
    parser = optparse.OptionParser()
    parser.add_option('-q', '--quality', dest='quality',
                      help='sets the quality of compression',
                      default='5',
                      nargs=1)

    options, arguments = parser.parse_args()

    try:
        global compression_quality
        compression_quality = int(options.quality)
    except TypeError:
        print('Invalid compression quality')
        exit(1)

    auth_reddit()
    auth_imgur()
    auth_db()
    while True:
        try:
            scan()
        except KeyboardInterrupt:
            break
        except Exception:
            traceback.print_exc()
        print('Running again in', pull_period, 'seconds')
        sql.commit()
        time.sleep(pull_period)


if __name__ == '__main__':
    main()
