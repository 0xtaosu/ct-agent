from flask import Flask, request, jsonify
import pandas as pd
from datetime import datetime, timedelta
import json
# from deepseal import DeepSealAPI
import threading
import queue
import logging
import os
import time
from openai import OpenAI
import schedule
from dotenv import load_dotenv

# 在文件开头加载环境变量
load_dotenv()

app = Flask(__name__)

# 创建一个队列用于存储接收到的数据
data_queue = queue.Queue()

# 设置日志配置
logging.basicConfig(
    filename='webhook.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class TwitterDataAnalyzer:
    def __init__(self, deepseal_key):
        # self.deepseal_api = DeepSealAPI(deepseal_key)
        self.data_file = "twitter_data.csv"
        # 初始化DataFrame
        self.df = pd.DataFrame(columns=['id', 'text', 'created_at', 'timestamp'])
        self.df.to_csv(self.data_file, index=False)

    def save_to_csv(self, data):
        """将数据保存为CSV文件"""
        try:
            new_data = pd.DataFrame([data])
            new_data['timestamp'] = pd.to_datetime(new_data['created_at'])
            new_data.to_csv(self.data_file, mode='a', header=False, index=False)
            print(f"数据已保存: {data['id']}")
        except Exception as e:
            print(f"保存数据失败: {str(e)}")

    def summarize_data(self, time_window):
        """使用DeepSeal总结指定时间窗口的数据"""
        try:
            df = pd.read_csv(self.data_file)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
            # 计算时间窗口
            end_time = datetime.now()
            if time_window == '5min':
                start_time = end_time - timedelta(minutes=5)
            elif time_window == '1hour':
                start_time = end_time - timedelta(hours=1)
            elif time_window == '24hour':
                start_time = end_time - timedelta(days=1)
            
            # 筛选时间范围内的数据
            filtered_data = df[(df['timestamp'] >= start_time) & 
                             (df['timestamp'] <= end_time)]
            
            if filtered_data.empty:
                return f"在{time_window}时间窗口内没有数据"

            # 构建Prompt
            prompt = f"""
            请总结以下时间段 ({start_time} 到 {end_time}) 的Twitter信息流中的关键信息：
            1. 识别主要话题和趋势
            2. 提取重要事件和新闻
            3. 分析情感倾向
            4. 总结用户反馈和讨论

            原始数据：
            {filtered_data['text'].to_string()}
            """
            
            # 调用DeepSeal进行总结
            summary = self.deepseal_api.generate(prompt)
            return summary
        except Exception as e:
            return f"总结数据失败: {str(e)}"

# 初始化分析器
analyzer = TwitterDataAnalyzer(deepseal_key="your_deepseal_key")

def validate_twitter_data(data):
    """验证推特数据的格式"""
    try:
        required_fields = ['id', 'text', 'created_at']
        return all(field in data for field in required_fields)
    except Exception as e:
        logging.error(f"数据验证错误: {str(e)}")
        return False

class TwitterDataProcessor:
    def __init__(self):
        self.data_dir = "data"
        self.twitter_file = os.path.join(self.data_dir, "twitter_data.csv")
        os.makedirs(self.data_dir, exist_ok=True)
        self.init_csv_file()
    
    def init_csv_file(self):
        """初始化CSV文件和列"""
        columns = [
            'timestamp',      # 事件发生时间
            'user_name',      # 用户名
            'event_type',     # 事件类型
            'content'         # 内容
        ]
        
        if not os.path.exists(self.twitter_file):
            pd.DataFrame(columns=columns).to_csv(self.twitter_file, index=False)
    
    def get_content(self, data, event_type):
        """根据事件类型提取相应的内容"""
        if event_type == 'new_tweet':
            tweet = data.get('tweet', {})
            # 如果是回复或引用，添加相关信息
            if tweet.get('is_reply') or tweet.get('is_quote'):
                return f"{data.get('title', '')} - {tweet.get('text', '')}"
            return tweet.get('text', '')
        
        elif event_type == 'new_description':
            return data.get('user', {}).get('description', '')
        
        elif event_type == 'new_follower':
            follow_user = data.get('follow_user', {})
            return f"关注了用户: {follow_user.get('name', '')}"
        
        return data.get('content', '')

    def process_webhook_data(self, data):
        """处理webhook数据"""
        try:
            event_type = data.get('push_type', '')
            user_data = data.get('user', {})
            
            # 获取事件时间
            if event_type == 'new_tweet':
                timestamp = datetime.fromtimestamp(data['tweet']['publish_time']).isoformat()
            else:
                timestamp = datetime.fromtimestamp(user_data.get('updated_at', datetime.now().timestamp())).isoformat()
            
            # 构建行数据
            row = {
                'timestamp': timestamp,
                'user_name': user_data.get('name', ''),
                'event_type': event_type,
                'content': self.get_content(data, event_type)
            }
            
            # 保存到CSV
            pd.DataFrame([row]).to_csv(self.twitter_file, mode='a', header=False, index=False)
            
            logging.info(f"数据已保存 - 事件类型: {event_type}")
            return True
            
        except Exception as e:
            logging.error(f"处理数据时出错: {str(e)}")
            return False

# 创建处理器实例
data_processor = TwitterDataProcessor()

@app.route('/webhook/twitter', methods=['POST'])
def webhook_receiver():
    """接收webhook推送的数据并处理"""
    try:
        logging.info("=== 收到新的 Webhook 请求 ===")
        logging.info(f"请求方法: {request.method}")
        logging.info(f"请求头: {dict(request.headers)}")
        
        json_data = request.json
        logging.info(f"JSON 数据: {json_data}")
        
        if data_processor.process_webhook_data(json_data):
            return jsonify({
                "status": "success",
                "message": "Data processed and saved",
                "timestamp": datetime.now().isoformat()
            }), 200
        else:
            return jsonify({
                "status": "error",
                "message": "Failed to process data"
            }), 500
            
    except Exception as e:
        logging.error(f"处理请求时发生错误: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

class TwitterSummarizer:
    def __init__(self):
        # 从环境变量获取 API key
        api_key = os.getenv('DEEPSEEK_API_KEY')
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY not found in environment variables")
            
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com"
        )
        self.last_summary_time = {
            '5min': datetime.now(),
            '1hour': datetime.now(),
            '6hour': datetime.now(),
            '24hour': datetime.now()
        }
        # 启动定时任务
        self.start_scheduled_summaries()
    
    def get_period_data(self, period):
        """获取指定时间段的新数据"""
        now = datetime.now()
        last_time = self.last_summary_time[period]
        
        try:
            df = pd.read_csv('data/twitter_data.csv')
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            new_data = df[df['timestamp'] > last_time]
            
            # 更新最后总结时间
            self.last_summary_time[period] = now
            
            return new_data
            
        except Exception as e:
            logging.error(f"获取{period}数据时出错: {str(e)}")
            return pd.DataFrame()

    def generate_summary(self, period):
        """使用 DeepSeek 生成总结"""
        try:
            df = self.get_period_data(period)
            if len(df) == 0:
                return f"在过去{period}内没有新的推文活动"

            # 准备提示信息
            events = df.to_dict('records')
            events_text = "\n".join([
                f"时间: {e['timestamp']}, 用户: {e['user_name']}, "
                f"事件: {e['event_type']}, 内容: {e['content']}"
                for e in events
            ])

            # 根据不同时间段设置提示
            prompts = {
                '5min': "请简要总结最近5分钟的Twitter活动要点。",
                '1hour': "请总结过去1小时的主要Twitter活动和趋势。",
                '6hour': "请分析过去6小时的Twitter活动，包括热门话题和重要互动。",
                '24hour': "请总结过去24小时的Twitter活动，分析主要话题走向。"
            }

            messages = [
                {"role": "system", "content": prompts[period]},
                {"role": "user", "content": f"请总结以下Twitter活动：\n{events_text}"}
            ]

            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                temperature=0.7,
                stream=False
            )

            return response.choices[0].message.content

        except Exception as e:
            error_msg = f"生成{period}总结时出错: {str(e)}"
            logging.error(error_msg)
            return error_msg

    def start_scheduled_summaries(self):
        """启动定时总结任务"""
        def run_schedule():
            while True:
                schedule.run_pending()
                time.sleep(1)

        def generate_and_print_summary(period):
            summary = self.generate_summary(period)
            print(f"\n=== {period} 定时总结 ===")
            print(f"总结时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(summary)
            print("="*50)

        # 设置定时任务
        schedule.every(5).minutes.do(lambda: generate_and_print_summary('5min'))
        schedule.every(1).hours.do(lambda: generate_and_print_summary('1hour'))
        schedule.every(6).hours.do(lambda: generate_and_print_summary('6hour'))
        schedule.every(24).hours.do(lambda: generate_and_print_summary('24hour'))

        # 在后台线程中运行定时任务
        threading.Thread(target=run_schedule, daemon=True).start()
        logging.info("定时总结任务已启动")

def process_data():
    """处理队列中的数据"""
    try:
        summarizer = TwitterSummarizer()
        
        while True:
            try:
                # 从队列中获取数据
                data = data_queue.get()
                # 保存数据
                analyzer.save_to_csv(data)
                
            except Exception as e:
                logging.error(f"处理数据失败: {str(e)}")
    except Exception as e:
        logging.error(f"初始化 TwitterSummarizer 失败: {str(e)}")

def start_server():
    """启动Flask服务器"""
    app.run(host='0.0.0.0', port=5000)


if __name__ == "__main__":
    # 创建并启动数据处理线程
    process_thread = threading.Thread(target=process_data)
    process_thread.daemon = True
    process_thread.start()
    
    # 启动Flask服务器
    start_server()