from flask import Flask, render_template, request, redirect, url_for, flash
from accounts.manager import AccountManager
from browser.multi_login import MultiLoginManager
import os

app = Flask(__name__)
app.secret_key = os.urandom(24)

account_manager = AccountManager()
multi_login_manager = MultiLoginManager()

@app.route('/')
def index():
    accounts = account_manager.get_accounts()
    return render_template('index.html', accounts=accounts)

@app.route('/add', methods=['GET', 'POST'])
def add_account():
    if request.method == 'POST':
        name = request.form['name']
        website = request.form['website']
        username = request.form['username']
        password = request.form['password']
        
        account = account_manager.add_account(name, website, username, password)
        flash('账户添加成功!')
        return redirect(url_for('index'))
    return render_template('add.html')

@app.route('/edit/<int:account_id>', methods=['GET', 'POST'])
def edit_account(account_id):
    account = account_manager.get_account(account_id)
    if not account:
        flash('账户不存在!')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        name = request.form['name']
        website = request.form['website']
        username = request.form['username']
        password = request.form['password']
        
        updated_account = account_manager.update_account(
            account_id, 
            name=name, 
            website=website, 
            username=username, 
            password=password
        )
        flash('账户更新成功!')
        return redirect(url_for('index'))
    
    return render_template('edit.html', account=account)

@app.route('/delete/<int:account_id>')
def delete_account(account_id):
    success = account_manager.delete_account(account_id)
    if success:
        flash('账户删除成功!')
    else:
        flash('账户删除失败!')
    return redirect(url_for('index'))

@app.route('/login/<int:account_id>')
def login_account(account_id):
    multi_login_manager.login_single_account(account_id)
    flash('正在登录账户...')
    return redirect(url_for('index'))

@app.route('/login-all')
def login_all_accounts():
    multi_login_manager.login_all_accounts()
    flash('正在登录所有账户...')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)