package com.bookreader.core

/**
 * 书籍数据模型 - Kotlin 版本
 * 与 Python core 模块的 Book 数据类对应
 */
data class Book(
    val id: String,
    val title: String,
    val author: String,
    val path: String,
    val format: String,
    val totalPages: Int,
    var currentPage: Int = 0,
    val bookmarks: MutableList<Int> = mutableListOf()
)

/**
 * 页面数据模型
 */
data class Page(
    val pageNum: Int,
    val content: String,
    val chapterTitle: String? = null
)
