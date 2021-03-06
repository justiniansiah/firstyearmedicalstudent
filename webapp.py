# Standard libary
import os
import os.path

# Third-party modules
from flask import Flask, jsonify, make_response, redirect, render_template, \
                  request, url_for
import click

# Local modules
from db_tools.db_downup import download_table, fetch_table, upload_table


# Init app
app = Flask(__name__)


@app.route('/')
def main_page():
    return render_template('title_page.html')


@app.route('/load')
def load():
    return render_template('load_account_page.html')


@app.route('/database')
@app.route('/database/<table_name>')
def debug_database(table_name=None):
    """Performs query to fetch all table rows.

    Args:
        table_name: Name of the table to fetch rows from.
                    Default: None
    """
    query_results = []
    if table_name:
        query_results = fetch_table(table_name)

    return render_template('debug_database.html', 
                           table_name=table_name, 
                           query_results=query_results)


@app.route('/database/<table_name>/upload', methods=['GET', 'POST'])
def debug_database_upload(table_name=None):
    """Accepts csv file to replace into target table.

    Args:
        table_name: Name of the table to upload and replace into.
                    Default: None

    Returns:
        JSON object containing the name of the uploaded file.
        Mainly just to trigger client-side JavaScript callback.
    """
    if (not table_name) or (request.method == 'GET'):
        return redirect(url_for('debug_database', table_name=table_name))    
    
    f = request.files['file']
    print('get file:', f.filename)
    upload_table(table_name, f)
    # return json response to trigger JavaScript `done` callback
    return jsonify([f.filename])


@app.route('/database/<table_name>/download')
def debug_database_download(table_name=None):
    """Downloads table data as csv file.
    
    Args:
        table_name: Name of the table to downlaod from.
                    Default: None

    Returns:
        302 Redirect to download the generated file.
    """
    if (not table_name):
        return redirect(url_for('debug_database', table_name=table_name))    
    
    output = download_table(table_name)
    csv_fname = table_name + '.csv'
    with open(os.path.join('static', csv_fname), 'w', encoding='utf-8') as f:
        f.write(output)
    return redirect(url_for('static', filename=csv_fname))


@app.cli.command(with_appcontext=True)
def render():
    """Pre-renders templates into a folder for easy preview

    You can't pass args from Flask CLI into this function so just change the
    settings below.
    """
    # Define the templates you want to render here
    templates = [
        ['debug_database.html', dict(
            table_name='snippets',
            query_results=[['this', 'is', 'a', 'sample', 'db', 'response']] + [[*'abcdef']] * 10
        )],
        'main_page.html'
    ]

    # Options
    output_folder='prerenders'
    update_gitignore=True

    # Shorthand
    osp = os.path

    with app.test_request_context('/'):

        basedir = osp.abspath(os.path.dirname(__file__))
        abs_outputfolder = osp.join(basedir, output_folder)

        # Prep target dir
        if not osp.exists(output_folder):
            os.mkdir(output_folder)

        click.echo('Pre-rendering...')
        for t in templates:
            # Echo to CLI for feedback
            click.echo('  {}'.format(str(t)))

            # Prep vars
            templatename = t
            options = dict()

            # If t is a list, first item should be template name, second
            # should be a dict of options to pass to render_template
            if type(t) == list:
                templatename, options = t

            with open(osp.join(abs_outputfolder, templatename), 
                      'w', encoding='utf-8') as f:
                s = render_template(templatename, **options)
                f.write(s.replace(r'/static/', r'../static/'))

    # Update .gitignore
    if not update_gitignore:
        return
    gitignore_path = osp.join(basedir, '.gitignore')
    addline = output_folder + r'/*'
    click.echo('Updating .gitignore...')
    with open(gitignore_path, 'a+') as f:
        for line in f.readlines():
            if line == addline:
                click.echo('  Prerender folder already ignored, skipping')
                break
        else:
            click.echo('  Updated.')
            f.write('\n' + addline)


if __name__ == '__main__':
    # Bind to env var PORT if defined, otherwise default to 5000.
    # https://stackoverflow.com/a/17276310
    port = int(os.environ.get('PORT', 5000))

    # Figure out if debugging is wanted
    debugging = int(os.environ.get('FLASK_DEBUG', 0))
    host = '127.0.0.1' if debugging else '0.0.0.0'

    app.run(host=host, port=port)