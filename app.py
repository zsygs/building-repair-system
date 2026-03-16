from flask import Flask, render_template, redirect, url_for, request, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy
import bcrypt
from datetime import datetime, timedelta

import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'instance', 'repair_system.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# 数据库模型
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 普通用户、审核人员、领导
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    def check_password(self, password):
        return bcrypt.checkpw(password.encode('utf-8'), self.password.encode('utf-8'))

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(200), nullable=False)
    budget = db.Column(db.Float, nullable=False)
    content = db.Column(db.Text, nullable=False)
    submitter_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='待审核')  # 待审核、审核中、已审核、待审批、已审批、已拒绝
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    comment = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(10), nullable=False)  # 通过、拒绝
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Approval(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    approver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    comment = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(10), nullable=False)  # 通过、拒绝
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# 创建数据库
with app.app_context():
    db.create_all()

# 路由
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('用户名或密码错误')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        
        if User.query.filter_by(username=username).first():
            flash('用户名已存在')
            return redirect(url_for('register'))
        
        user = User(username=username, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash('注册成功，请登录')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    search = request.args.get('search', '')
    user_search = request.args.get('user_search', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    
    if current_user.role == '普通用户':
        # 普通用户只能看到自己的项目
        query = Project.query.filter_by(submitter_id=current_user.id)
    elif current_user.role == '审核人员':
        # 审核人员可以看到所有项目
        query = Project.query
    elif current_user.role == '领导':
        # 领导只能看到已审核的项目（避免跳级）
        query = Project.query.filter((Project.status == '待审批') | (Project.status == '已审批') | (Project.status == '已拒绝'))
    
    # 应用搜索过滤
    if search:
        query = query.filter(
            (Project.name.like(f'%{search}%')) |
            (Project.location.like(f'%{search}%'))
        )
    
    # 应用用户搜索过滤
    if user_search:
        # 搜索申请人或审核人
        submitter_ids = User.query.filter(User.username.like(f'%{user_search}%')).with_entities(User.id).all()
        submitter_ids = [id[0] for id in submitter_ids]
        
        # 搜索申请人
        query = query.filter(
            (Project.submitter_id.in_(submitter_ids))
        )
    
    # 应用时间过滤
    if start_date:
        try:
            query = query.filter(Project.created_at >= datetime.strptime(start_date, '%Y-%m-%d'))
        except ValueError:
            pass
    if end_date:
        try:
            # 添加一天，使结束日期包含在内
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
            end_date_obj += timedelta(days=1)
            query = query.filter(Project.created_at < end_date_obj)
        except ValueError:
            pass
    
    projects = query.all()
    
    # 获取每个项目的相关用户信息
    project_data = []
    for project in projects:
        submitter = User.query.get(project.submitter_id)
        review = Review.query.filter_by(project_id=project.id).first()
        reviewer = User.query.get(review.reviewer_id) if review else None
        approval = Approval.query.filter_by(project_id=project.id).first()
        approver = User.query.get(approval.approver_id) if approval else None
        project_data.append({
            'project': project,
            'submitter': submitter,
            'review': review,
            'reviewer': reviewer,
            'approval': approval,
            'approver': approver
        })
    
    if current_user.role == '普通用户':
        return render_template('user_dashboard.html', project_data=project_data)
    elif current_user.role == '审核人员':
        return render_template('reviewer_dashboard.html', project_data=project_data)
    elif current_user.role == '领导':
        return render_template('leader_dashboard.html', project_data=project_data)

@app.route('/project/create', methods=['GET', 'POST'])
@login_required
def create_project():
    if current_user.role != '普通用户':
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        name = request.form['name']
        location = request.form['location']
        budget = float(request.form['budget'])
        content = request.form['content']
        
        project = Project(
            name=name,
            location=location,
            budget=budget,
            content=content,
            submitter_id=current_user.id,
            status='待审核'
        )
        db.session.add(project)
        db.session.commit()
        flash('项目创建成功')
        return redirect(url_for('dashboard'))
    
    return render_template('create_project.html')

@app.route('/project/<int:project_id>')
@login_required
def project_detail(project_id):
    project = Project.query.get(project_id)
    if not project:
        flash('项目不存在')
        return redirect(url_for('dashboard'))
    
    submitter = User.query.get(project.submitter_id)
    review = Review.query.filter_by(project_id=project_id).first()
    reviewer = User.query.get(review.reviewer_id) if review else None
    approval = Approval.query.filter_by(project_id=project_id).first()
    approver = User.query.get(approval.approver_id) if approval else None
    
    return render_template('project_detail.html', project=project, submitter=submitter, review=review, reviewer=reviewer, approval=approval, approver=approver)

@app.route('/project/<int:project_id>/review', methods=['GET', 'POST'])
@login_required
def review_project(project_id):
    if current_user.role != '审核人员':
        return redirect(url_for('dashboard'))
    
    project = Project.query.get(project_id)
    if not project or project.status != '待审核':
        flash('项目不存在或状态不正确')
        return redirect(url_for('dashboard'))
    
    submitter = User.query.get(project.submitter_id)
    
    if request.method == 'POST':
        status = request.form['status']
        comment = request.form['comment']
        
        review = Review(
            project_id=project_id,
            reviewer_id=current_user.id,
            comment=comment,
            status=status
        )
        db.session.add(review)
        
        if status == '通过':
            project.status = '待审批'
        else:
            project.status = '已拒绝'
        
        db.session.commit()
        flash('审核完成')
        return redirect(url_for('dashboard'))
    
    return render_template('review_project.html', project=project, submitter=submitter)

@app.route('/project/<int:project_id>/approve', methods=['GET', 'POST'])
@login_required
def approve_project(project_id):
    if current_user.role != '领导':
        return redirect(url_for('dashboard'))
    
    project = Project.query.get(project_id)
    if not project or project.status != '待审批':
        flash('项目不存在或状态不正确')
        return redirect(url_for('dashboard'))
    
    submitter = User.query.get(project.submitter_id)
    review = Review.query.filter_by(project_id=project_id).first()
    reviewer = User.query.get(review.reviewer_id) if review else None
    
    if request.method == 'POST':
        status = request.form['status']
        comment = request.form['comment']
        
        approval = Approval(
            project_id=project_id,
            approver_id=current_user.id,
            comment=comment,
            status=status
        )
        db.session.add(approval)
        
        if status == '通过':
            project.status = '已审批'
        else:
            project.status = '已拒绝'
        
        db.session.commit()
        flash('审批完成')
        return redirect(url_for('dashboard'))
    
    return render_template('approve_project.html', project=project, submitter=submitter, review=review, reviewer=reviewer)

# 左侧导航栏功能路由
@app.route('/dashboard/pending-approval')
@login_required
def pending_approval():
    if current_user.role != '领导':
        return redirect(url_for('dashboard'))
    
    # 只显示待审批的项目
    projects = Project.query.filter_by(status='待审批').all()
    project_data = []
    for project in projects:
        submitter = User.query.get(project.submitter_id)
        review = Review.query.filter_by(project_id=project.id).first()
        reviewer = User.query.get(review.reviewer_id) if review else None
        approval = Approval.query.filter_by(project_id=project.id).first()
        approver = User.query.get(approval.approver_id) if approval else None
        project_data.append({
            'project': project,
            'submitter': submitter,
            'review': review,
            'reviewer': reviewer,
            'approval': approval,
            'approver': approver
        })
    
    return render_template('leader_dashboard.html', project_data=project_data, active_page='pending-approval')

@app.route('/dashboard/approval-history')
@login_required
def approval_history():
    if current_user.role != '领导':
        return redirect(url_for('dashboard'))
    
    # 显示已审批或已拒绝的项目
    projects = Project.query.filter((Project.status == '已审批') | (Project.status == '已拒绝')).all()
    project_data = []
    for project in projects:
        submitter = User.query.get(project.submitter_id)
        review = Review.query.filter_by(project_id=project.id).first()
        reviewer = User.query.get(review.reviewer_id) if review else None
        approval = Approval.query.filter_by(project_id=project.id).first()
        approver = User.query.get(approval.approver_id) if approval else None
        project_data.append({
            'project': project,
            'submitter': submitter,
            'review': review,
            'reviewer': reviewer,
            'approval': approval,
            'approver': approver
        })
    
    return render_template('leader_dashboard.html', project_data=project_data, active_page='approval-history')

@app.route('/dashboard/pending-review')
@login_required
def pending_review():
    if current_user.role != '审核人员':
        return redirect(url_for('dashboard'))
    
    # 只显示待审核的项目
    projects = Project.query.filter_by(status='待审核').all()
    project_data = []
    for project in projects:
        submitter = User.query.get(project.submitter_id)
        review = Review.query.filter_by(project_id=project.id).first()
        reviewer = User.query.get(review.reviewer_id) if review else None
        approval = Approval.query.filter_by(project_id=project.id).first()
        approver = User.query.get(approval.approver_id) if approval else None
        project_data.append({
            'project': project,
            'submitter': submitter,
            'review': review,
            'reviewer': reviewer,
            'approval': approval,
            'approver': approver
        })
    
    return render_template('reviewer_dashboard.html', project_data=project_data, active_page='pending-review')

@app.route('/dashboard/review-history')
@login_required
def review_history():
    if current_user.role != '审核人员':
        return redirect(url_for('dashboard'))
    
    # 显示已审核的项目
    projects = Project.query.filter((Project.status == '已审核') | (Project.status == '待审批') | (Project.status == '已审批') | (Project.status == '已拒绝')).all()
    project_data = []
    for project in projects:
        submitter = User.query.get(project.submitter_id)
        review = Review.query.filter_by(project_id=project.id).first()
        reviewer = User.query.get(review.reviewer_id) if review else None
        approval = Approval.query.filter_by(project_id=project.id).first()
        approver = User.query.get(approval.approver_id) if approval else None
        project_data.append({
            'project': project,
            'submitter': submitter,
            'review': review,
            'reviewer': reviewer,
            'approval': approval,
            'approver': approver
        })
    
    return render_template('reviewer_dashboard.html', project_data=project_data, active_page='review-history')

@app.route('/help')
@login_required
def help_center():
    return render_template('help_center.html')

@app.route('/user/settings', methods=['GET', 'POST'])
@login_required
def user_settings():
    if request.method == 'POST':
        current_password = request.form['current_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']
        
        # 验证当前密码
        if not current_user.check_password(current_password):
            flash('当前密码错误')
            return redirect(url_for('user_settings'))
        
        # 验证新密码和确认密码
        if new_password != confirm_password:
            flash('新密码和确认密码不一致')
            return redirect(url_for('user_settings'))
        
        # 更新密码
        current_user.set_password(new_password)
        db.session.commit()
        flash('密码更改成功')
        return redirect(url_for('user_settings'))
    
    return render_template('user_settings.html')

@app.route('/user/history')
@login_required
def user_history():
    if current_user.role != '普通用户':
        return redirect(url_for('dashboard'))
    
    # 获取用户的所有项目
    projects = Project.query.filter_by(submitter_id=current_user.id).all()
    project_data = []
    for project in projects:
        submitter = User.query.get(project.submitter_id)
        review = Review.query.filter_by(project_id=project.id).first()
        reviewer = User.query.get(review.reviewer_id) if review else None
        approval = Approval.query.filter_by(project_id=project.id).first()
        approver = User.query.get(approval.approver_id) if approval else None
        project_data.append({
            'project': project,
            'submitter': submitter,
            'review': review,
            'reviewer': reviewer,
            'approval': approval,
            'approver': approver
        })
    
    return render_template('user_history.html', project_data=project_data)

@app.route('/project/<int:project_id>/delete')
@login_required
def delete_project(project_id):
    project = Project.query.get(project_id)
    if not project:
        flash('项目不存在')
        return redirect(url_for('dashboard'))
    
    # 只有项目的提交者可以删除项目
    if project.submitter_id != current_user.id:
        flash('没有权限删除此项目')
        return redirect(url_for('dashboard'))
    
    # 删除相关的审核和审批记录
    Review.query.filter_by(project_id=project_id).delete()
    Approval.query.filter_by(project_id=project_id).delete()
    
    # 删除项目
    db.session.delete(project)
    db.session.commit()
    
    flash('项目删除成功')
    return redirect(url_for('user_history'))

if __name__ == '__main__':
    app.run(debug=True)